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
        runs_qs = self.runs.order_by("created_at")

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
                    messages.append(_normalize_message(msg))
                    seen_message_hashes.add(msg_hash)

            # Get output messages (assistant responses, tool calls, etc.)
            output_data = run.output or {}
            output_messages = output_data.get("final_messages", [])

            for msg in output_messages:
                msg_hash = _message_hash(msg)
                if msg_hash not in seen_message_hashes:
                    messages.append(_normalize_message(msg))
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


def _normalize_message(msg: dict) -> dict:
    """
    Normalize a message to the framework-neutral Message format.

    Ensures consistent structure regardless of how it was stored.
    """
    normalized = {
        "role": msg.get("role", "user"),
    }

    # Handle content (can be string, dict, or list)
    content = msg.get("content")
    if content is not None:
        normalized["content"] = content

    # Optional fields - only include if present
    if msg.get("name"):
        normalized["name"] = msg["name"]

    if msg.get("tool_call_id"):
        normalized["tool_call_id"] = msg["tool_call_id"]

    if msg.get("tool_calls"):
        normalized["tool_calls"] = msg["tool_calls"]

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

