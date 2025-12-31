"""
API views for agent runtime.
"""

import asyncio
import json
from uuid import UUID

from django.http import StreamingHttpResponse
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated

from django_agent_runtime.models import AgentRun, AgentConversation, AgentEvent
from django_agent_runtime.models.base import RunStatus
from django_agent_runtime.api.serializers import (
    AgentRunSerializer,
    AgentRunCreateSerializer,
    AgentRunDetailSerializer,
    AgentConversationSerializer,
    AgentEventSerializer,
)
from django_agent_runtime.conf import runtime_settings, get_hook


class AgentConversationViewSet(viewsets.ModelViewSet):
    """
    ViewSet for managing agent conversations.
    """

    serializer_class = AgentConversationSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        """Filter conversations by user."""
        return AgentConversation.objects.filter(user=self.request.user)

    def perform_create(self, serializer):
        """Set user on creation."""
        serializer.save(user=self.request.user)


class AgentRunViewSet(viewsets.ModelViewSet):
    """
    ViewSet for managing agent runs.

    Endpoints:
    - POST /runs/ - Create a new run
    - GET /runs/ - List runs
    - GET /runs/{id}/ - Get run details
    - POST /runs/{id}/cancel/ - Cancel a run
    - GET /runs/{id}/events/ - Get events (SSE)
    """

    permission_classes = [IsAuthenticated]

    def get_serializer_class(self):
        if self.action == "create":
            return AgentRunCreateSerializer
        elif self.action == "retrieve":
            return AgentRunDetailSerializer
        return AgentRunSerializer

    def get_queryset(self):
        """Filter runs by user's conversations."""
        return AgentRun.objects.filter(
            conversation__user=self.request.user
        ).select_related("conversation")

    def create(self, request, *args, **kwargs):
        """Create a new agent run."""
        serializer = self.get_serializer(data=request.data)
        serializer.validate(request.data)
        serializer.is_valid(raise_exception=True)

        data = serializer.validated_data

        # Check authorization
        settings = runtime_settings()
        authz_hook = get_hook(settings.AUTHZ_HOOK)
        if authz_hook and not authz_hook(request.user, "create_run", data):
            return Response(
                {"error": "Not authorized to create this run"},
                status=status.HTTP_403_FORBIDDEN,
            )

        # Check quota
        quota_hook = get_hook(settings.QUOTA_HOOK)
        if quota_hook and not quota_hook(request.user, data["agent_key"]):
            return Response(
                {"error": "Quota exceeded"},
                status=status.HTTP_429_TOO_MANY_REQUESTS,
            )

        # Get or create conversation
        conversation = None
        if data.get("conversation_id"):
            try:
                conversation = AgentConversation.objects.get(
                    id=data["conversation_id"],
                    user=request.user,
                )
            except AgentConversation.DoesNotExist:
                return Response(
                    {"error": "Conversation not found"},
                    status=status.HTTP_404_NOT_FOUND,
                )

        # Check idempotency
        if data.get("idempotency_key"):
            existing = AgentRun.objects.filter(
                idempotency_key=data["idempotency_key"]
            ).first()
            if existing:
                return Response(
                    AgentRunSerializer(existing).data,
                    status=status.HTTP_200_OK,
                )

        # Create the run
        run = AgentRun.objects.create(
            conversation=conversation,
            agent_key=data["agent_key"],
            input={
                "messages": data["messages"],
                "params": data.get("params", {}),
            },
            max_attempts=data.get("max_attempts", 3),
            idempotency_key=data.get("idempotency_key"),
            metadata={
                **data.get("metadata", {}),
                "conversation_id": str(conversation.id) if conversation else None,
            },
        )

        # Enqueue to Redis if using Redis queue
        if settings.QUEUE_BACKEND == "redis_streams":
            asyncio.run(self._enqueue_to_redis(run))

        return Response(
            AgentRunSerializer(run).data,
            status=status.HTTP_201_CREATED,
        )

    async def _enqueue_to_redis(self, run: AgentRun):
        """Enqueue run to Redis stream."""
        from django_agent_runtime.runtime.queue.redis_streams import RedisStreamsQueue

        settings = runtime_settings()
        queue = RedisStreamsQueue(redis_url=settings.REDIS_URL)
        await queue.enqueue(run.id, run.agent_key)
        await queue.close()

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        """Cancel a running agent run."""
        run = self.get_object()

        if run.is_terminal:
            return Response(
                {"error": "Run is already complete"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Request cancellation
        from django.utils import timezone

        run.cancel_requested_at = timezone.now()
        run.save(update_fields=["cancel_requested_at"])

        return Response({"status": "cancellation_requested"})

    @action(detail=True, methods=["get"])
    def events(self, request, pk=None):
        """
        Stream events for a run via Server-Sent Events (SSE).

        Query params:
        - from_seq: Start from this sequence number (default: 0)
        """
        run = self.get_object()
        from_seq = int(request.query_params.get("from_seq", 0))

        settings = runtime_settings()
        if not settings.ENABLE_SSE:
            return Response(
                {"error": "SSE streaming is disabled"},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        response = StreamingHttpResponse(
            self._event_stream(run.id, from_seq),
            content_type="text/event-stream",
        )
        response["Cache-Control"] = "no-cache"
        response["X-Accel-Buffering"] = "no"
        return response

    def _event_stream(self, run_id: UUID, from_seq: int):
        """Generate SSE event stream."""
        import time
        from django_agent_runtime.runtime.events import get_event_bus

        settings = runtime_settings()

        # Use sync event fetching for SSE (simpler than async in Django views)
        current_seq = from_seq
        keepalive_interval = settings.SSE_KEEPALIVE_SECONDS

        while True:
            # Get new events from database
            events = list(
                AgentEvent.objects.filter(
                    run_id=run_id,
                    seq__gte=current_seq,
                ).order_by("seq")
            )

            for event in events:
                data = {
                    "run_id": str(event.run_id),
                    "seq": event.seq,
                    "type": event.event_type,
                    "payload": event.payload,
                    "ts": event.timestamp.isoformat(),
                }
                yield f"data: {json.dumps(data)}\n\n"
                current_seq = event.seq + 1

                # Check for terminal events
                if event.event_type in (
                    "run.succeeded",
                    "run.failed",
                    "run.cancelled",
                    "run.timed_out",
                ):
                    return

            # Check if run is complete
            try:
                run = AgentRun.objects.get(id=run_id)
                if run.is_terminal:
                    return
            except AgentRun.DoesNotExist:
                return

            # Send keepalive
            yield f": keepalive\n\n"

            # Wait before polling again
            time.sleep(0.5)


# Async SSE view for ASGI deployments
async def async_event_stream(request, run_id: str):
    """
    Async SSE endpoint for streaming events.

    Use this with ASGI servers (uvicorn, daphne) for better performance.
    """
    from django.http import StreamingHttpResponse
    from asgiref.sync import sync_to_async

    run_id = UUID(run_id)
    from_seq = int(request.GET.get("from_seq", 0))

    # Check authorization
    @sync_to_async
    def check_access():
        try:
            run = AgentRun.objects.select_related("conversation").get(id=run_id)
            if run.conversation and run.conversation.user != request.user:
                return None
            return run
        except AgentRun.DoesNotExist:
            return None

    run = await check_access()
    if not run:
        from django.http import JsonResponse

        return JsonResponse({"error": "Not found"}, status=404)

    async def event_generator():
        from django_agent_runtime.runtime.events import get_event_bus

        settings = runtime_settings()
        event_bus = get_event_bus(settings.EVENT_BUS_BACKEND)

        try:
            async for event in event_bus.subscribe(run_id, from_seq=from_seq):
                data = event.to_dict()
                yield f"data: {json.dumps(data)}\n\n"

                # Check for terminal events
                if event.event_type in (
                    "run.succeeded",
                    "run.failed",
                    "run.cancelled",
                    "run.timed_out",
                ):
                    break
        finally:
            await event_bus.close()

    response = StreamingHttpResponse(
        event_generator(),
        content_type="text/event-stream",
    )
    response["Cache-Control"] = "no-cache"
    response["X-Accel-Buffering"] = "no"
    return response
