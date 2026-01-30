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

from django.http import StreamingHttpResponse, FileResponse
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.parsers import MultiPartParser, FormParser

from django_agent_runtime.models import AgentRun, AgentConversation, AgentEvent, AgentFile, AgentTaskList, AgentTask
from django_agent_runtime.storage import get_storage_backend
from django_agent_runtime.models.base import RunStatus
from django_agent_runtime.api.serializers import (
    AgentRunSerializer,
    AgentRunCreateSerializer,
    AgentRunDetailSerializer,
    AgentConversationSerializer,
    AgentConversationDetailSerializer,
    AgentEventSerializer,
    AgentFileSerializer,
    AgentFileUploadSerializer,
    AgentTaskListSerializer,
    AgentTaskListCreateSerializer,
    AgentTaskSerializer,
    AgentTaskCreateSerializer,
    AgentTaskUpdateSerializer,
)
from django_agent_runtime.api.permissions import get_anonymous_session
from django_agent_runtime.conf import runtime_settings, get_hook
from django_agent_runtime.runtime.llm import list_models_for_ui, DEFAULT_MODEL


class BaseAgentConversationViewSet(viewsets.ModelViewSet):
    """
    Base ViewSet for managing agent conversations.

    Inherit from this and set your own permission_classes and authentication_classes.
    """

    serializer_class = AgentConversationSerializer

    def get_serializer_class(self):
        """Use detail serializer for retrieve action to include messages."""
        if self.action == "retrieve":
            return AgentConversationDetailSerializer
        return AgentConversationSerializer

    def get_queryset(self):
        """Filter conversations by user or anonymous session, and optionally by agent_key."""
        if self.request.user and self.request.user.is_authenticated:
            queryset = AgentConversation.objects.filter(user=self.request.user)
        else:
            # For anonymous sessions, filter by anonymous_session_id
            session = get_anonymous_session(self.request)
            if session:
                queryset = AgentConversation.objects.filter(anonymous_session_id=session.id)
            else:
                return AgentConversation.objects.none()

        # Filter by agent_key if provided
        agent_key = self.request.query_params.get("agent_key")
        if agent_key:
            queryset = queryset.filter(agent_key=agent_key)

        return queryset.order_by("-updated_at")

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
        # Conversations are always created - this enables conversation history by default
        conversation = None
        session = get_anonymous_session(request)

        if data.get("conversation_id"):
            # Try to get existing conversation
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
        else:
            # Auto-create a new conversation
            # This ensures conversation history works by default
            conversation = AgentConversation.objects.create(
                agent_key=data["agent_key"],
                user=request.user if request.user and request.user.is_authenticated else None,
                anonymous_session_id=session.id if session else None,
                title="",  # Will be updated later based on first message
                metadata=data.get("metadata", {}),
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

        # Handle edit/retry: mark old runs as superseded
        supersede_from_index = data.get("supersede_from_message_index")
        if supersede_from_index is not None and conversation:
            self._supersede_runs_from_index(conversation, run, supersede_from_index)

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

    def _supersede_runs_from_index(
        self, conversation: AgentConversation, new_run: AgentRun, from_message_index: int
    ):
        """
        Mark runs as superseded when edit/retry is used.

        This finds all runs that contributed messages at or after the given index
        and marks them as superseded by the new run. This ensures get_message_history()
        returns only the canonical conversation history.

        Args:
            conversation: The conversation containing the runs
            new_run: The new run that supersedes the old ones
            from_message_index: The message index from which to supersede
        """
        # Get all non-superseded runs in chronological order
        runs = list(
            conversation.runs.filter(superseded_by__isnull=True)
            .exclude(id=new_run.id)
            .order_by("created_at")
        )

        # Track cumulative message count to find which runs to supersede
        cumulative_message_count = 0
        runs_to_supersede = []

        for run in runs:
            # Count messages contributed by this run
            input_messages = (run.input or {}).get("messages", [])
            output_messages = (run.output or {}).get("final_messages", [])

            run_start_index = cumulative_message_count
            run_message_count = len(input_messages) + len(output_messages)

            # If this run's messages start at or after the supersede index,
            # or if the supersede index falls within this run's messages,
            # mark it as superseded
            if run_start_index >= from_message_index or (
                run_start_index < from_message_index
                and run_start_index + run_message_count > from_message_index
            ):
                runs_to_supersede.append(run)

            cumulative_message_count += run_message_count

        # Mark all identified runs as superseded
        if runs_to_supersede:
            run_ids = [r.id for r in runs_to_supersede]
            AgentRun.objects.filter(id__in=run_ids).update(superseded_by=new_run)

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
                    # Use named events so addEventListener works in browser
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
                # Use named SSE events for proper addEventListener support
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


class BaseModelsViewSet(viewsets.ViewSet):
    """
    ViewSet for listing available LLM models.

    Provides a list of supported models that can be used in the model selector UI.
    """

    def list(self, request):
        """List all available models."""
        models = list_models_for_ui()
        return Response({
            "models": models,
            "default": DEFAULT_MODEL,
        })



class BaseAgentFileViewSet(viewsets.ModelViewSet):
    """
    ViewSet for managing agent files.

    Provides CRUD operations for file uploads, plus download and thumbnail actions.
    Supports both authenticated users and anonymous sessions.
    """

    serializer_class = AgentFileSerializer
    parser_classes = [MultiPartParser, FormParser]

    def get_queryset(self):
        """Get files owned by the current user or anonymous session."""
        user = self.request.user
        if user.is_authenticated:
            return AgentFile.objects.filter(user=user).order_by("-created_at")
        else:
            session_id = get_anonymous_session(self.request)
            if session_id:
                return AgentFile.objects.filter(
                    anonymous_session_id=session_id
                ).order_by("-created_at")
            return AgentFile.objects.none()

    def get_serializer_class(self):
        """Use upload serializer for create action."""
        if self.action == "create":
            return AgentFileUploadSerializer
        return AgentFileSerializer

    def create(self, request, *args, **kwargs):
        """Handle file upload."""
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        uploaded_file = serializer.validated_data["file"]
        conversation_id = serializer.validated_data.get("conversation_id")

        # Get storage backend
        storage = get_storage_backend()

        # Save file to storage
        try:
            stored_file = storage.save(
                file_obj=uploaded_file,
                filename=uploaded_file.name,
                content_type=uploaded_file.content_type or "application/octet-stream",
            )
        except Exception as e:
            return Response(
                {"error": f"Failed to save file: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        # Create database record
        user = request.user if request.user.is_authenticated else None
        anonymous_session_id = (
            None if user else get_anonymous_session(request)
        )

        # Get conversation if provided
        conversation = None
        if conversation_id:
            try:
                conversation = AgentConversation.objects.get(id=conversation_id)
            except AgentConversation.DoesNotExist:
                pass

        agent_file = AgentFile.objects.create(
            user=user,
            anonymous_session_id=anonymous_session_id,
            conversation=conversation,
            original_filename=uploaded_file.name,
            stored_path=stored_file.path,
            content_type=stored_file.content_type,
            size_bytes=stored_file.size_bytes,
            storage_backend=stored_file.backend,
        )

        output_serializer = AgentFileSerializer(agent_file)
        return Response(output_serializer.data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["get"])
    def download(self, request, pk=None):
        """Download the file."""
        agent_file = self.get_object()
        storage = get_storage_backend()

        try:
            file_obj = storage.get(agent_file.stored_path)
            response = FileResponse(
                file_obj,
                content_type=agent_file.content_type,
                as_attachment=True,
                filename=agent_file.original_filename,
            )
            return response
        except Exception as e:
            return Response(
                {"error": f"Failed to retrieve file: {str(e)}"},
                status=status.HTTP_404_NOT_FOUND,
            )

    @action(detail=True, methods=["get"])
    def thumbnail(self, request, pk=None):
        """Get thumbnail for the file (if available)."""
        agent_file = self.get_object()

        if not agent_file.thumbnail_path:
            return Response(
                {"error": "No thumbnail available"},
                status=status.HTTP_404_NOT_FOUND,
            )

        storage = get_storage_backend()
        try:
            file_obj = storage.get(agent_file.thumbnail_path)
            return FileResponse(
                file_obj,
                content_type="image/png",
            )
        except Exception as e:
            return Response(
                {"error": f"Failed to retrieve thumbnail: {str(e)}"},
                status=status.HTTP_404_NOT_FOUND,
            )

    def destroy(self, request, *args, **kwargs):
        """Delete file from storage and database."""
        agent_file = self.get_object()
        storage = get_storage_backend()

        # Delete from storage
        try:
            storage.delete(agent_file.stored_path)
            if agent_file.thumbnail_path:
                storage.delete(agent_file.thumbnail_path)
        except Exception:
            pass  # Continue even if storage delete fails

        return super().destroy(request, *args, **kwargs)


class BaseAgentTaskListViewSet(viewsets.ModelViewSet):
    """
    ViewSet for managing agent task lists.

    Task lists are per-user and track the agent's progress on complex work.
    Each user typically has one active task list.

    Endpoints:
    - GET /tasks/ - Get the current user's task list (creates one if none exists)
    - POST /tasks/ - Create a new task list
    - GET /tasks/{id}/ - Get a specific task list
    - PUT /tasks/{id}/ - Update a task list
    - DELETE /tasks/{id}/ - Delete a task list
    - POST /tasks/{id}/add_task/ - Add a task to the list
    - PUT /tasks/{id}/update_task/{task_id}/ - Update a task
    - DELETE /tasks/{id}/remove_task/{task_id}/ - Remove a task
    - POST /tasks/{id}/reorganize/ - Reorganize tasks (reorder, reparent)
    """

    serializer_class = AgentTaskListSerializer

    def get_serializer_class(self):
        if self.action == "create":
            return AgentTaskListCreateSerializer
        return AgentTaskListSerializer

    def get_queryset(self):
        """Get task lists for the current user."""
        if self.request.user and self.request.user.is_authenticated:
            return AgentTaskList.objects.filter(user=self.request.user)
        return AgentTaskList.objects.none()

    def list(self, request, *args, **kwargs):
        """
        Get the current user's task list.

        If no task list exists, creates one automatically.
        Returns a single task list (not a paginated list).
        """
        if not request.user or not request.user.is_authenticated:
            return Response(
                {"error": "Authentication required"},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        # Get or create the user's task list
        task_list, created = AgentTaskList.objects.get_or_create(
            user=request.user,
            defaults={"name": "Current Task List"},
        )

        serializer = self.get_serializer(task_list)
        return Response(serializer.data)

    def create(self, request, *args, **kwargs):
        """Create a new task list for the user."""
        if not request.user or not request.user.is_authenticated:
            return Response(
                {"error": "Authentication required"},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        serializer = AgentTaskListCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        # Get conversation if provided
        conversation = None
        if serializer.validated_data.get("conversation_id"):
            try:
                conversation = AgentConversation.objects.get(
                    id=serializer.validated_data["conversation_id"],
                    user=request.user,
                )
            except AgentConversation.DoesNotExist:
                pass

        task_list = AgentTaskList.objects.create(
            user=request.user,
            name=serializer.validated_data.get("name", "Current Task List"),
            conversation=conversation,
            metadata=serializer.validated_data.get("metadata", {}),
        )

        return Response(
            AgentTaskListSerializer(task_list).data,
            status=status.HTTP_201_CREATED,
        )

    @action(detail=True, methods=["post"])
    def add_task(self, request, pk=None):
        """Add a task to the task list."""
        task_list = self.get_object()

        serializer = AgentTaskCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        # Validate parent if provided
        parent = None
        if data.get("parent_id"):
            try:
                parent = AgentTask.objects.get(
                    id=data["parent_id"],
                    task_list=task_list,
                )
            except AgentTask.DoesNotExist:
                return Response(
                    {"error": "Parent task not found"},
                    status=status.HTTP_404_NOT_FOUND,
                )

        task = AgentTask.objects.create(
            task_list=task_list,
            name=data["name"],
            description=data.get("description", ""),
            state=data.get("state", "not_started"),
            parent=parent,
            order=data.get("order", 0),
            metadata=data.get("metadata", {}),
        )

        # Update task list timestamp
        task_list.save()

        return Response(
            AgentTaskSerializer(task).data,
            status=status.HTTP_201_CREATED,
        )

    @action(detail=True, methods=["put"], url_path="update_task/(?P<task_id>[^/.]+)")
    def update_task(self, request, pk=None, task_id=None):
        """Update a task in the task list."""
        task_list = self.get_object()

        try:
            task = AgentTask.objects.get(id=task_id, task_list=task_list)
        except AgentTask.DoesNotExist:
            return Response(
                {"error": "Task not found"},
                status=status.HTTP_404_NOT_FOUND,
            )

        serializer = AgentTaskUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        # Update fields if provided
        if "name" in data:
            task.name = data["name"]
        if "description" in data:
            task.description = data["description"]
        if "state" in data:
            task.state = data["state"]
        if "order" in data:
            task.order = data["order"]
        if "metadata" in data:
            task.metadata = data["metadata"]

        # Handle parent change
        if "parent_id" in data:
            if data["parent_id"] is None:
                task.parent = None
            else:
                try:
                    parent = AgentTask.objects.get(
                        id=data["parent_id"],
                        task_list=task_list,
                    )
                    # Prevent circular references
                    if parent.id == task.id:
                        return Response(
                            {"error": "Task cannot be its own parent"},
                            status=status.HTTP_400_BAD_REQUEST,
                        )
                    task.parent = parent
                except AgentTask.DoesNotExist:
                    return Response(
                        {"error": "Parent task not found"},
                        status=status.HTTP_404_NOT_FOUND,
                    )

        task.save()
        task_list.save()  # Update timestamp

        return Response(AgentTaskSerializer(task).data)

    @action(detail=True, methods=["delete"], url_path="remove_task/(?P<task_id>[^/.]+)")
    def remove_task(self, request, pk=None, task_id=None):
        """Remove a task from the task list."""
        task_list = self.get_object()

        try:
            task = AgentTask.objects.get(id=task_id, task_list=task_list)
        except AgentTask.DoesNotExist:
            return Response(
                {"error": "Task not found"},
                status=status.HTTP_404_NOT_FOUND,
            )

        task.delete()
        task_list.save()  # Update timestamp

        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=["post"])
    def reorganize(self, request, pk=None):
        """
        Reorganize tasks in the task list.

        Accepts a list of task updates with new order and parent_id values.
        Format: {"tasks": [{"id": "...", "order": 0, "parent_id": null}, ...]}
        """
        task_list = self.get_object()

        tasks_data = request.data.get("tasks", [])
        if not tasks_data:
            return Response(
                {"error": "No tasks provided"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Validate all task IDs exist
        task_ids = [t.get("id") for t in tasks_data]
        existing_tasks = {
            str(t.id): t
            for t in AgentTask.objects.filter(id__in=task_ids, task_list=task_list)
        }

        if len(existing_tasks) != len(task_ids):
            return Response(
                {"error": "Some tasks not found"},
                status=status.HTTP_404_NOT_FOUND,
            )

        # Update each task
        for task_data in tasks_data:
            task = existing_tasks[task_data["id"]]
            if "order" in task_data:
                task.order = task_data["order"]
            if "parent_id" in task_data:
                if task_data["parent_id"] is None:
                    task.parent = None
                elif task_data["parent_id"] in existing_tasks:
                    task.parent = existing_tasks[task_data["parent_id"]]
            task.save()

        task_list.save()  # Update timestamp

        return Response(AgentTaskListSerializer(task_list).data)

    @action(detail=True, methods=["post"])
    def clear(self, request, pk=None):
        """Clear all tasks from the task list."""
        task_list = self.get_object()
        task_list.tasks.all().delete()
        task_list.save()

        return Response(AgentTaskListSerializer(task_list).data)
