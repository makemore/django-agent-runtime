"""
Base API views for agent runtime.

These are abstract base classes - inherit from them in your project
and set your own authentication_classes and permission_classes.

Example:
    from django_agent_runtime.api.views import BaseAgentRunViewSet
    from myapp.permissions import MyPermission

    class AgentRunViewSet(BaseAgentRunViewSet):
        permission_classes = [MyPermission]
"""

import asyncio
import json
from uuid import UUID

from django.http import StreamingHttpResponse
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response

from django_agent_runtime.models import AgentRun, AgentConversation, AgentEvent
from django_agent_runtime.models.base import RunStatus
from django_agent_runtime.api.serializers import (
    AgentRunSerializer,
    AgentRunCreateSerializer,
    AgentRunDetailSerializer,
    AgentConversationSerializer,
    AgentEventSerializer,
)
from django_agent_runtime.api.permissions import get_anonymous_session
from django_agent_runtime.conf import runtime_settings, get_hook


class BaseAgentConversationViewSet(viewsets.ModelViewSet):
    """
    Base ViewSet for managing agent conversations.

    Inherit from this and set your own permission_classes and authentication_classes.
    """

    serializer_class = AgentConversationSerializer

    def get_queryset(self):
        """Filter conversations by user or anonymous session."""
        if self.request.user and self.request.user.is_authenticated:
            return AgentConversation.objects.filter(user=self.request.user)

        # For anonymous sessions, filter by anonymous_session_id
        session = get_anonymous_session(self.request)
        if session:
            return AgentConversation.objects.filter(anonymous_session_id=session.id)

        return AgentConversation.objects.none()

    def perform_create(self, serializer):
        """Set user or anonymous session on creation."""
        if self.request.user and self.request.user.is_authenticated:
            serializer.save(user=self.request.user)
        else:
            session = get_anonymous_session(self.request)
            if session:
                # Use the setter which handles both FK and UUID field
                serializer.save(anonymous_session=session)
            else:
                serializer.save()


class BaseAgentRunViewSet(viewsets.ModelViewSet):
    """
    Base ViewSet for managing agent runs.

    Inherit from this and set your own permission_classes and authentication_classes.

    Endpoints:
    - POST /runs/ - Create a new run
    - GET /runs/ - List runs
    - GET /runs/{id}/ - Get run details
    - POST /runs/{id}/cancel/ - Cancel a run
    """

    def get_serializer_class(self):
        if self.action == "create":
            return AgentRunCreateSerializer
        elif self.action == "retrieve":
            return AgentRunDetailSerializer
        return AgentRunSerializer

    def get_queryset(self):
        """Filter runs by user's conversations or anonymous session."""
        from django.db.models import Q

        if self.request.user and self.request.user.is_authenticated:
            # Include runs with user's conversations OR runs without conversation
            # that were created by this user (stored in metadata)
            return AgentRun.objects.filter(
                Q(conversation__user=self.request.user) |
                Q(conversation__isnull=True, metadata__user_id=self.request.user.id)
            ).select_related("conversation")

        # For anonymous sessions - filter by anonymous_session_id
        session = get_anonymous_session(self.request)
        if session:
            return AgentRun.objects.filter(
                Q(conversation__anonymous_session_id=session.id) |
                Q(conversation__isnull=True, metadata__anonymous_token=session.token)
            ).select_related("conversation")

        return AgentRun.objects.none()

    def create(self, request, *args, **kwargs):
        """Create a new agent run."""
        serializer = self.get_serializer(data=request.data)
        serializer.validate(request.data)
        serializer.is_valid(raise_exception=True)

        data = serializer.validated_data

        # Check authorization hooks if configured
        settings = runtime_settings()
        if request.user and request.user.is_authenticated:
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
        session = get_anonymous_session(request)

        if data.get("conversation_id"):
            try:
                if request.user and request.user.is_authenticated:
                    conversation = AgentConversation.objects.get(
                        id=data["conversation_id"],
                        user=request.user,
                    )
                elif session:
                    conversation = AgentConversation.objects.get(
                        id=data["conversation_id"],
                        anonymous_session_id=session.id,
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

        # Build metadata with session/user info
        metadata = {
            **data.get("metadata", {}),
            "conversation_id": str(conversation.id) if conversation else None,
        }
        if request.user and request.user.is_authenticated:
            metadata["user_id"] = request.user.id
        if session:
            metadata["anonymous_token"] = session.token

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
            metadata=metadata,
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


def sync_event_stream(request, run_id: str):
    """
    Sync SSE endpoint for streaming events.

    This is a plain Django view (not DRF) to avoid content negotiation issues.

    Authorization is checked by verifying the user owns the run (via conversation
    or metadata). The outer project controls authentication via middleware.

    For token-based auth with SSE (where headers can't be set), pass the token
    as a query parameter: ?token=<auth_token>

    Query Parameters:
        from_seq: Start from this sequence number (default: 0)
        include_debug: Include debug-level events (default: false)
        include_all: Include all events including internal (default: false)
    """
    import time
    from django.http import JsonResponse

    try:
        run_uuid = UUID(run_id)
    except ValueError:
        return JsonResponse({"error": "Invalid run ID"}, status=400)

    from_seq = int(request.GET.get("from_seq", 0))
    include_debug = request.GET.get("include_debug", "").lower() in ("true", "1", "yes")
    include_all = request.GET.get("include_all", "").lower() in ("true", "1", "yes")

    try:
        run = AgentRun.objects.select_related("conversation").get(id=run_uuid)
    except AgentRun.DoesNotExist:
        return JsonResponse({"error": "Run not found"}, status=404)

    # Check access - user must own the run
    has_access = False
    
    # Get authenticated user (may be set by middleware or we need to check token)
    user = request.user if hasattr(request, 'user') else None
    
    # Support token auth via query param for SSE (browsers can't set headers on EventSource)
    if (not user or not user.is_authenticated) and request.GET.get('token'):
        from rest_framework.authtoken.models import Token
        try:
            token = Token.objects.select_related('user').get(key=request.GET.get('token'))
            user = token.user
        except Token.DoesNotExist:
            pass
    
    if user and user.is_authenticated:
        # User owns the conversation
        if run.conversation and run.conversation.user == user:
            has_access = True
        # Run without conversation - check metadata
        elif not run.conversation and run.metadata.get("user_id") == user.id:
            has_access = True
        # Allow access to runs without ownership info (backwards compat)
        elif not run.conversation and "user_id" not in run.metadata:
            has_access = True
    
    # Check anonymous session if configured
    if not has_access:
        anonymous_token = request.headers.get('X-Anonymous-Token') or request.GET.get('anonymous_token')
        if anonymous_token:
            from django_agent_runtime.api.permissions import _get_anonymous_session_model
            AnonymousSession = _get_anonymous_session_model()
            if AnonymousSession:
                try:
                    session = AnonymousSession.objects.get(token=anonymous_token)
                    is_expired = getattr(session, 'is_expired', False)
                    if not is_expired:
                        # Check by anonymous_session_id (UUID field)
                        if run.conversation and run.conversation.anonymous_session_id == session.id:
                            has_access = True
                        elif not run.conversation and run.metadata.get("anonymous_token") == anonymous_token:
                            has_access = True
                except AnonymousSession.DoesNotExist:
                    pass

    if not has_access:
        return JsonResponse({"error": "Not authorized"}, status=403)

    settings = runtime_settings()
    if not settings.ENABLE_SSE:
        return JsonResponse({"error": "SSE streaming is disabled"}, status=503)

    # Import visibility helper
    from django_agent_runtime.conf import get_event_visibility

    def should_include_event(event_type: str) -> bool:
        """Determine if an event should be included based on visibility settings."""
        if include_all:
            return True

        visibility_level, ui_visible = get_event_visibility(event_type)

        if visibility_level == "internal":
            return False
        elif visibility_level == "debug":
            return include_debug or settings.DEBUG_MODE
        else:  # "user"
            return True

    def event_generator():
        current_seq = from_seq

        while True:
            # Get new events from database
            events = list(
                AgentEvent.objects.filter(
                    run_id=run_uuid,
                    seq__gte=current_seq,
                ).order_by("seq")
            )

            for event in events:
                current_seq = event.seq + 1

                # Check for terminal events (always process these for loop control)
                is_terminal = event.event_type in (
                    "run.succeeded",
                    "run.failed",
                    "run.cancelled",
                    "run.timed_out",
                )

                # Filter by visibility
                if should_include_event(event.event_type):
                    # Get visibility info for the response
                    visibility_level, ui_visible = get_event_visibility(event.event_type)

                    data = {
                        "run_id": str(event.run_id),
                        "seq": event.seq,
                        "type": event.event_type,
                        "payload": event.payload,
                        "ts": event.timestamp.isoformat(),
                        "visibility_level": visibility_level,
                        "ui_visible": ui_visible,
                    }
                    # Use named events so browsers can use addEventListener
                    yield f"event: {event.event_type}\ndata: {json.dumps(data)}\n\n"

                if is_terminal:
                    return

            # Check if run is complete
            try:
                run_check = AgentRun.objects.get(id=run_uuid)
                if run_check.is_terminal:
                    return
            except AgentRun.DoesNotExist:
                return

            # Send keepalive
            yield ": keepalive\n\n"

            # Wait before polling again
            time.sleep(0.5)

    response = StreamingHttpResponse(
        event_generator(),
        content_type="text/event-stream",
    )
    response["Cache-Control"] = "no-cache"
    response["X-Accel-Buffering"] = "no"
    response["Access-Control-Allow-Origin"] = "*"
    return response


async def async_event_stream(request, run_id: str):
    """
    Async SSE endpoint for streaming events.

    Use this with ASGI servers (uvicorn, daphne) for better performance.
    """
    from django.http import StreamingHttpResponse, JsonResponse
    from asgiref.sync import sync_to_async

    try:
        run_uuid = UUID(run_id)
    except ValueError:
        return JsonResponse({"error": "Invalid run ID"}, status=400)

    from_seq = int(request.GET.get("from_seq", 0))

    @sync_to_async
    def check_access():
        try:
            run = AgentRun.objects.select_related("conversation").get(id=run_uuid)
        except AgentRun.DoesNotExist:
            return None
            
        user = request.user if hasattr(request, 'user') else None
        
        if user and user.is_authenticated:
            if run.conversation and run.conversation.user == user:
                return run
            elif not run.conversation and run.metadata.get("user_id") == user.id:
                return run
            elif not run.conversation and "user_id" not in run.metadata:
                return run
        
        return None

    run = await check_access()
    if not run:
        return JsonResponse({"error": "Not found or not authorized"}, status=404)

    async def event_generator():
        from django_agent_runtime.runtime.events import get_event_bus

        settings = runtime_settings()
        event_bus = get_event_bus(settings.EVENT_BUS_BACKEND)

        try:
            async for event in event_bus.subscribe(run_uuid, from_seq=from_seq):
                data = event.to_dict()
                event_type = data.get("type", "message")
                # Use named events so browsers can use addEventListener
                yield f"event: {event_type}\ndata: {json.dumps(data)}\n\n"

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
