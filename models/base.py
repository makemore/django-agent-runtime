"""
Abstract base models for the Agent Runtime.

These can be extended by host projects for customization.
Use Pattern A (concrete models) by default, Pattern B (swappable) for advanced use.
"""

import uuid
from django.db import models
from django.conf import settings


class RunStatus(models.TextChoices):
    """Status choices for agent runs."""

    QUEUED = "queued", "Queued"
    RUNNING = "running", "Running"
    SUCCEEDED = "succeeded", "Succeeded"
    FAILED = "failed", "Failed"
    CANCELLED = "cancelled", "Cancelled"
    TIMED_OUT = "timed_out", "Timed Out"


class AbstractAgentConversation(models.Model):
    """
    Abstract model for grouping related agent runs.

    A conversation represents a multi-turn interaction with an agent.
    Supports both authenticated users and anonymous sessions.

    Anonymous Session Support:
        The abstract model stores anonymous_session_id as a UUID field.
        This allows the runtime to work without requiring a specific session model.

        To enable anonymous sessions:
        1. Set ANONYMOUS_SESSION_MODEL in DJANGO_AGENT_RUNTIME settings
        2. The model must have a 'token' field and optionally 'is_expired' property

        For a proper FK relationship, create a custom conversation model::

            class MyAgentConversation(AbstractAgentConversation):
                anonymous_session = models.ForeignKey(
                    "myapp.AnonymousSession",
                    on_delete=models.SET_NULL,
                    null=True, blank=True,
                )
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # Optional user association (nullable for system-initiated conversations)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="agent_conversations",
    )

    # Optional anonymous session association (stores session ID as UUID)
    # This allows anonymous sessions without requiring a specific model FK
    anonymous_session_id = models.UUIDField(
        null=True,
        blank=True,
        db_index=True,
        help_text="UUID of the anonymous session (if using anonymous sessions)",
    )

    # Agent identification
    agent_key = models.CharField(
        max_length=100,
        db_index=True,
        help_text="Identifier for the agent runtime to use",
    )

    # Conversation state
    title = models.CharField(max_length=255, blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True
        ordering = ["-created_at"]
        verbose_name = "Agent Conversation"
        verbose_name_plural = "Agent Conversations"

    def __str__(self):
        return f"{self.agent_key} - {self.id}"

    @property
    def owner(self):
        """Return the owner (User or AnonymousSession) of this conversation."""
        if self.user:
            return self.user
        # Try to get anonymous_session FK if it exists (custom model)
        if hasattr(self, 'anonymous_session') and self.anonymous_session:
            return self.anonymous_session
        # Fall back to resolving from anonymous_session_id
        return self.get_anonymous_session()

    def get_anonymous_session(self):
        """
        Get the anonymous session object if configured and available.

        Returns the session object or None if:
        - No anonymous_session_id is set
        - ANONYMOUS_SESSION_MODEL is not configured
        - Session doesn't exist or is expired
        """
        if not self.anonymous_session_id:
            return None

        # Check if we have a direct FK (custom model)
        if hasattr(self, 'anonymous_session'):
            return self.anonymous_session

        # Resolve from configured model
        from django_agent_runtime.conf import runtime_settings

        settings_obj = runtime_settings()
        model_path = settings_obj.ANONYMOUS_SESSION_MODEL

        if not model_path:
            return None

        try:
            from django.apps import apps
            app_label, model_name = model_path.rsplit('.', 1)
            AnonymousSession = apps.get_model(app_label, model_name)
            session = AnonymousSession.objects.get(id=self.anonymous_session_id)

            # Check if expired
            if hasattr(session, 'is_expired') and session.is_expired:
                return None

            return session
        except Exception:
            return None

    def get_message_history(self, include_failed_runs: bool = False) -> list[dict]:
        """
        Get the full message history across all runs in this conversation.

        Returns messages in chronological order, including:
        - Input messages from each run
        - Assistant responses (including tool calls)
        - Tool results

        Args:
            include_failed_runs: If True, include messages from failed runs.
                                 Default is False (only successful runs).

        Returns:
            List of Message dicts in the framework-neutral format:
            [
                {"role": "user", "content": "..."},
                {"role": "assistant", "content": "...", "tool_calls": [...]},
                {"role": "tool", "content": "...", "tool_call_id": "..."},
                ...
            ]
        """
        from django_agent_runtime.models.base import RunStatus

        # Get runs in chronological order
        # Exclude superseded runs - these were replaced by edit/retry
        runs_qs = self.runs.filter(superseded_by__isnull=True).order_by("created_at")

        if not include_failed_runs:
            runs_qs = runs_qs.filter(status=RunStatus.SUCCEEDED)

        messages = []
        seen_message_hashes = set()  # Avoid duplicates from overlapping input

        for run in runs_qs:
            # Get input messages (user messages that started this run)
            input_data = run.input or {}
            input_messages = input_data.get("messages", [])

            # Add input messages (avoiding duplicates)
            for msg in input_messages:
                # Create a hash to detect duplicates
                msg_hash = _message_hash(msg)
                if msg_hash not in seen_message_hashes:
                    normalized = _normalize_message(msg)
                    if normalized is not None:
                        messages.append(normalized)
                        seen_message_hashes.add(msg_hash)

            # Get output messages (assistant responses, tool calls, etc.)
            output_data = run.output or {}
            output_messages = output_data.get("final_messages", [])

            for msg in output_messages:
                msg_hash = _message_hash(msg)
                if msg_hash not in seen_message_hashes:
                    normalized = _normalize_message(msg)
                    if normalized is not None:
                        messages.append(normalized)
                        seen_message_hashes.add(msg_hash)

        return messages

    def get_last_assistant_message(self) -> dict | None:
        """
        Get the most recent assistant message from the conversation.

        Returns:
            The last assistant message dict, or None if no assistant messages exist.
        """
        messages = self.get_message_history()
        for msg in reversed(messages):
            if msg.get("role") == "assistant":
                return msg
        return None


def _message_hash(msg: dict) -> str:
    """Create a hash for deduplication of messages."""
    import hashlib
    import json

    # Use role + content + tool_call_id for uniqueness
    key_parts = [
        msg.get("role", ""),
        str(msg.get("content", "")),
        msg.get("tool_call_id", ""),
    ]
    # Include tool_calls if present
    if msg.get("tool_calls"):
        key_parts.append(json.dumps(msg["tool_calls"], sort_keys=True))

    key = "|".join(key_parts)
    return hashlib.md5(key.encode()).hexdigest()


def _normalize_message(msg: dict) -> dict | None:
    """
    Normalize a message to the framework-neutral Message format.

    Ensures consistent structure regardless of how it was stored.
    Returns None for messages that should be filtered out (e.g., empty content
    without tool_calls).
    """
    role = msg.get("role", "user")
    content = msg.get("content")
    tool_calls = msg.get("tool_calls")
    tool_call_id = msg.get("tool_call_id")

    # Skip messages with empty/None content unless they have tool_calls or are tool results
    # Anthropic requires non-empty content for all messages except:
    # - Assistant messages with tool_calls (content can be empty)
    # - The final assistant message (content can be empty)
    if not content and content != 0:  # Allow 0 as valid content
        # Assistant messages with tool_calls are valid even without content
        if role == "assistant" and tool_calls:
            pass  # Allow through
        # Tool messages need tool_call_id, content can be empty result
        elif role == "tool" and tool_call_id:
            content = content if content else ""  # Ensure string, not None
        else:
            # Skip user/system messages with empty content
            return None

    normalized = {
        "role": role,
    }

    # Handle content (can be string, dict, or list)
    if content is not None:
        normalized["content"] = content

    # Optional fields - only include if present
    if msg.get("name"):
        normalized["name"] = msg["name"]

    if tool_call_id:
        normalized["tool_call_id"] = tool_call_id

    if tool_calls:
        normalized["tool_calls"] = tool_calls

    if msg.get("metadata"):
        normalized["metadata"] = msg["metadata"]

    return normalized


class AbstractAgentRun(models.Model):
    """
    Abstract model for a single agent execution.

    This is the core model - tracks status, input/output, retries, and leasing.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # Relationship to conversation (optional)
    # Note: concrete model defines the FK to avoid circular imports
    # conversation = models.ForeignKey(...)

    # Agent identification
    agent_key = models.CharField(
        max_length=100,
        db_index=True,
        help_text="Identifier for the agent runtime to use",
    )

    # Status tracking
    status = models.CharField(
        max_length=20,
        choices=RunStatus.choices,
        default=RunStatus.QUEUED,
        db_index=True,
    )

    # Input/Output (the canonical schema)
    input = models.JSONField(
        default=dict,
        help_text='{"messages": [...], "params": {...}}',
    )
    output = models.JSONField(
        default=dict,
        blank=True,
        help_text="Final output from the agent",
    )

    # Error tracking
    error = models.JSONField(
        default=dict,
        blank=True,
        help_text='{"type": "", "message": "", "stack": "", "retriable": true}',
    )

    # Retry configuration
    attempt = models.PositiveIntegerField(default=1)
    max_attempts = models.PositiveIntegerField(default=3)

    # Lease management (for distributed workers)
    lease_owner = models.CharField(
        max_length=100,
        blank=True,
        db_index=True,
        help_text="Worker ID that owns this run",
    )
    lease_expires_at = models.DateTimeField(
        null=True,
        blank=True,
        db_index=True,
        help_text="When the lease expires",
    )

    # Idempotency
    idempotency_key = models.CharField(
        max_length=255,
        null=True,
        blank=True,
        unique=True,
        help_text="Client-provided key for idempotent requests",
    )

    # Cancellation
    cancel_requested_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When cancellation was requested",
    )

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    # Extensibility
    metadata = models.JSONField(default=dict, blank=True)

    # Superseding (for edit/retry functionality)
    # When a user edits or retries a message, the old run is marked as superseded
    # by the new run. This allows get_message_history() to return only the
    # canonical conversation history.
    superseded_by = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="supersedes",
        help_text="If set, this run was superseded by another run (edit/retry)",
    )

    class Meta:
        abstract = True
        ordering = ["-created_at"]
        verbose_name = "Agent Run"
        verbose_name_plural = "Agent Runs"
        indexes = [
            models.Index(fields=["status", "lease_expires_at"]),
            models.Index(fields=["agent_key", "status"]),
        ]

    def __str__(self):
        return f"{self.agent_key} - {self.status} - {self.id}"

    @property
    def is_terminal(self) -> bool:
        """Check if the run is in a terminal state."""
        return self.status in {
            RunStatus.SUCCEEDED,
            RunStatus.FAILED,
            RunStatus.CANCELLED,
            RunStatus.TIMED_OUT,
        }


class AbstractAgentEvent(models.Model):
    """
    Abstract model for agent events (append-only log).

    Events are the communication channel between workers and UI.
    Strictly increasing seq per run, exactly one terminal event.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # Relationship to run (concrete model defines FK)
    # run = models.ForeignKey(...)

    # Event ordering
    seq = models.PositiveIntegerField(
        db_index=True,
        help_text="Strictly increasing sequence number per run",
    )

    # Event data
    event_type = models.CharField(
        max_length=50,
        db_index=True,
        help_text="Event type (e.g., run.started, assistant.message)",
    )
    payload = models.JSONField(default=dict)

    # Timestamp
    timestamp = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        abstract = True
        ordering = ["seq"]
        verbose_name = "Agent Event"
        verbose_name_plural = "Agent Events"

    def __str__(self):
        return f"{self.event_type} (seq={self.seq})"


class AbstractAgentCheckpoint(models.Model):
    """
    Abstract model for state checkpoints.

    Checkpoints allow recovery from failures mid-run.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # Relationship to run (concrete model defines FK)
    # run = models.ForeignKey(...)

    # Checkpoint data
    state = models.JSONField(
        help_text="Serialized agent state for recovery",
    )

    # Ordering
    seq = models.PositiveIntegerField(
        help_text="Checkpoint sequence number",
    )

    # Timestamp
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        abstract = True
        ordering = ["-seq"]
        verbose_name = "Agent Checkpoint"
        verbose_name_plural = "Agent Checkpoints"

    def __str__(self):
        return f"Checkpoint {self.seq}"


class TaskState(models.TextChoices):
    """Status choices for tasks."""

    NOT_STARTED = "not_started", "Not Started"
    IN_PROGRESS = "in_progress", "In Progress"
    COMPLETE = "complete", "Complete"
    CANCELLED = "cancelled", "Cancelled"


class AbstractAgentTaskList(models.Model):
    """
    Abstract model for a user's task list.

    Task lists are per-user (not per-conversation) and track the agent's
    progress on complex, long-running work. Each user has one active task list.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # Owner - task lists are per-user
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="agent_task_lists",
    )

    # Task list metadata
    name = models.CharField(
        max_length=255,
        default="Current Task List",
        help_text="Name of the task list",
    )

    # Optional association with a conversation (for context)
    # Note: Task list is per-user, but can be associated with a conversation
    # for context about what work is being tracked
    conversation = models.ForeignKey(
        "AgentConversation",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="task_lists",
        help_text="Optional conversation this task list is associated with",
    )

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # Extensibility
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        abstract = True
        ordering = ["-updated_at"]
        verbose_name = "Agent Task List"
        verbose_name_plural = "Agent Task Lists"

    def __str__(self):
        return f"{self.name} ({self.user})"

    def get_tasks_tree(self) -> list[dict]:
        """
        Get tasks as a nested tree structure.

        Returns a list of root tasks, each with a 'children' key containing
        nested subtasks.
        """
        tasks = list(self.tasks.all().order_by("created_at"))
        task_map = {task.id: {"task": task, "children": []} for task in tasks}

        roots = []
        for task in tasks:
            node = task_map[task.id]
            if task.parent_id and task.parent_id in task_map:
                task_map[task.parent_id]["children"].append(node)
            else:
                roots.append(node)

        return roots

    def get_progress(self) -> dict:
        """
        Get progress statistics for the task list.

        Returns:
            {
                "total": int,
                "completed": int,
                "in_progress": int,
                "not_started": int,
                "cancelled": int,
                "percent_complete": float,
            }
        """
        tasks = self.tasks.all()
        total = tasks.count()
        completed = tasks.filter(state=TaskState.COMPLETE).count()
        in_progress = tasks.filter(state=TaskState.IN_PROGRESS).count()
        not_started = tasks.filter(state=TaskState.NOT_STARTED).count()
        cancelled = tasks.filter(state=TaskState.CANCELLED).count()

        return {
            "total": total,
            "completed": completed,
            "in_progress": in_progress,
            "not_started": not_started,
            "cancelled": cancelled,
            "percent_complete": (completed / total * 100) if total > 0 else 0,
        }


class AbstractAgentTask(models.Model):
    """
    Abstract model for a single task in a task list.

    Tasks can be nested (parent_id) to create hierarchical task structures.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # Parent task list
    # Note: concrete model defines the FK to avoid circular imports
    # task_list = models.ForeignKey(...)

    # Task content
    name = models.CharField(
        max_length=500,
        help_text="Short name/title of the task",
    )
    description = models.TextField(
        blank=True,
        default="",
        help_text="Detailed description of the task",
    )

    # State
    state = models.CharField(
        max_length=20,
        choices=TaskState.choices,
        default=TaskState.NOT_STARTED,
        db_index=True,
    )

    # Hierarchy - tasks can have subtasks
    parent = models.ForeignKey(
        "self",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="subtasks",
        help_text="Parent task (for nested tasks)",
    )

    # Ordering within the list/parent
    order = models.PositiveIntegerField(
        default=0,
        help_text="Order within the task list or parent task",
    )

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    completed_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When the task was marked complete",
    )

    # Extensibility
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        abstract = True
        ordering = ["order", "created_at"]
        verbose_name = "Agent Task"
        verbose_name_plural = "Agent Tasks"

    def __str__(self):
        state_icon = {
            TaskState.NOT_STARTED: "[ ]",
            TaskState.IN_PROGRESS: "[/]",
            TaskState.COMPLETE: "[x]",
            TaskState.CANCELLED: "[-]",
        }.get(self.state, "[ ]")
        return f"{state_icon} {self.name}"

    def save(self, *args, **kwargs):
        # Auto-set completed_at when state changes to COMPLETE
        if self.state == TaskState.COMPLETE and not self.completed_at:
            from django.utils import timezone
            self.completed_at = timezone.now()
        elif self.state != TaskState.COMPLETE:
            self.completed_at = None
        super().save(*args, **kwargs)


class AbstractAgentFile(models.Model):
    """
    Abstract model for file storage and processing.

    Tracks uploaded files, their processing status, and extracted content.
    Integrates with agent_runtime_core file processing module.
    """

    class ProcessingStatus(models.TextChoices):
        PENDING = "pending", "Pending"
        PROCESSING = "processing", "Processing"
        COMPLETED = "completed", "Completed"
        FAILED = "failed", "Failed"

    class StorageBackend(models.TextChoices):
        LOCAL = "local", "Local Filesystem"
        S3 = "s3", "Amazon S3"
        GCS = "gcs", "Google Cloud Storage"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # File identification
    filename = models.CharField(
        max_length=255,
        help_text="Stored filename (may be sanitized/renamed)",
    )
    original_filename = models.CharField(
        max_length=255,
        help_text="Original filename as uploaded",
    )

    # File metadata
    content_type = models.CharField(
        max_length=255,
        help_text="MIME type of the file",
    )
    size_bytes = models.PositiveBigIntegerField(
        help_text="File size in bytes",
    )

    # Storage location
    storage_backend = models.CharField(
        max_length=20,
        choices=StorageBackend.choices,
        default=StorageBackend.LOCAL,
        help_text="Storage backend type",
    )
    storage_path = models.CharField(
        max_length=1024,
        help_text="Path or key within the storage backend",
    )

    # Processing state
    processing_status = models.CharField(
        max_length=20,
        choices=ProcessingStatus.choices,
        default=ProcessingStatus.PENDING,
        help_text="Current processing status",
    )
    error_message = models.TextField(
        blank=True,
        default="",
        help_text="Error message if processing failed",
    )

    # Processed content
    extracted_text = models.TextField(
        blank=True,
        default="",
        help_text="Text extracted from the file",
    )
    processed_data = models.JSONField(
        default=dict,
        blank=True,
        help_text="Additional processed data (OCR results, vision analysis, etc.)",
    )

    # Optional thumbnail for images/documents
    thumbnail_path = models.CharField(
        max_length=1024,
        blank=True,
        default="",
        help_text="Path to thumbnail image if generated",
    )

    # File metadata from processing
    file_metadata = models.JSONField(
        default=dict,
        blank=True,
        help_text="Metadata extracted from the file (dimensions, page count, etc.)",
    )

    # Ownership (optional - concrete model may add FK to conversation)
    # conversation = models.ForeignKey(...)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="%(class)s_files",
        help_text="User who uploaded the file",
    )
    anonymous_session_id = models.UUIDField(
        null=True,
        blank=True,
        db_index=True,
        help_text="Anonymous session ID for unauthenticated users",
    )

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True
        ordering = ["-created_at"]
        verbose_name = "Agent File"
        verbose_name_plural = "Agent Files"

    def __str__(self):
        return f"{self.original_filename} ({self.processing_status})"

    @property
    def is_processed(self) -> bool:
        """Check if file has been successfully processed."""
        return self.processing_status == self.ProcessingStatus.COMPLETED

    @property
    def is_image(self) -> bool:
        """Check if file is an image."""
        return self.content_type.startswith("image/")

    @property
    def is_document(self) -> bool:
        """Check if file is a document (PDF, Word, etc.)."""
        doc_types = [
            "application/pdf",
            "application/msword",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "application/vnd.ms-excel",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ]
        return self.content_type in doc_types

    def get_download_url(self) -> str:
        """Get URL for downloading the file. Override in concrete class if needed."""
        from django.urls import reverse
        return reverse("agent-files-download", kwargs={"pk": str(self.id)})

