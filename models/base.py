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

    # Optional anonymous session association
    # Note: Concrete model should define this FK to avoid import issues
    # anonymous_session = models.ForeignKey(...)

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
        return self.user or getattr(self, 'anonymous_session', None)


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

