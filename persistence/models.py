"""
Django models for the persistence layer.

These models back the Django implementations of the agent-runtime-core
persistence stores.
"""

import uuid
from django.db import models
from django.conf import settings


class Memory(models.Model):
    """
    Key-value memory storage for agents.
    
    Stores arbitrary JSON-serializable values keyed by string.
    Scoped to a user for multi-tenant support.
    """
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="agent_memories",
    )
    key = models.CharField(max_length=255, db_index=True)
    value = models.JSONField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        app_label = "django_agent_runtime"
        db_table = "agent_runtime_memory"
        unique_together = [("user", "key")]
        verbose_name = "Agent Memory"
        verbose_name_plural = "Agent Memories"
    
    def __str__(self):
        return f"{self.key} ({self.user})"


class PersistenceConversation(models.Model):
    """
    Conversation storage for the persistence layer.

    This is separate from AgentConversation to support the agent-runtime-core
    persistence interface which has different semantics.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="persistence_conversations",
    )
    title = models.CharField(max_length=255, blank=True)
    agent_key = models.CharField(max_length=100, blank=True, db_index=True)
    summary = models.TextField(blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    # Branching/forking support
    parent_conversation_id = models.UUIDField(null=True, blank=True, db_index=True)
    active_branch_id = models.UUIDField(null=True, blank=True)

    class Meta:
        app_label = "django_agent_runtime"
        db_table = "agent_runtime_persistence_conversation"
        ordering = ["-updated_at"]
        verbose_name = "Persistence Conversation"
        verbose_name_plural = "Persistence Conversations"

    def __str__(self):
        return f"{self.title or 'Untitled'} ({self.id})"


class PersistenceMessage(models.Model):
    """
    Message within a persistence conversation.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    conversation = models.ForeignKey(
        PersistenceConversation,
        on_delete=models.CASCADE,
        related_name="messages",
    )
    role = models.CharField(max_length=20)  # system, user, assistant, tool
    content = models.JSONField()  # Can be string, dict, or list
    tool_calls = models.JSONField(default=list, blank=True)
    tool_call_id = models.CharField(max_length=255, blank=True)
    model = models.CharField(max_length=100, blank=True)
    usage = models.JSONField(default=dict, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    timestamp = models.DateTimeField(auto_now_add=True, db_index=True)

    # Branching support
    parent_message_id = models.UUIDField(null=True, blank=True, db_index=True)
    branch_id = models.UUIDField(null=True, blank=True, db_index=True)

    class Meta:
        app_label = "django_agent_runtime"
        db_table = "agent_runtime_persistence_message"
        ordering = ["timestamp"]
        verbose_name = "Persistence Message"
        verbose_name_plural = "Persistence Messages"

    def __str__(self):
        return f"{self.role}: {str(self.content)[:50]}"


class TaskStateChoices(models.TextChoices):
    """Task state choices matching agent_runtime_core.persistence.TaskState."""
    
    NOT_STARTED = "not_started", "Not Started"
    IN_PROGRESS = "in_progress", "In Progress"
    COMPLETE = "complete", "Complete"
    CANCELLED = "cancelled", "Cancelled"


class PersistenceTaskList(models.Model):
    """
    Task list for tracking agent work.
    """
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="persistence_task_lists",
    )
    name = models.CharField(max_length=255)
    conversation_id = models.UUIDField(null=True, blank=True, db_index=True)
    run_id = models.UUIDField(null=True, blank=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        app_label = "django_agent_runtime"
        db_table = "agent_runtime_persistence_task_list"
        ordering = ["-updated_at"]
        verbose_name = "Persistence Task List"
        verbose_name_plural = "Persistence Task Lists"
    
    def __str__(self):
        return self.name


class PersistenceTask(models.Model):
    """
    Individual task within a task list.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    task_list = models.ForeignKey(
        PersistenceTaskList,
        on_delete=models.CASCADE,
        related_name="tasks",
    )
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    state = models.CharField(
        max_length=20,
        choices=TaskStateChoices.choices,
        default=TaskStateChoices.NOT_STARTED,
    )
    parent_id = models.UUIDField(null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # Dependencies and scheduling
    dependencies = models.JSONField(default=list, blank=True)  # List of task UUIDs
    priority = models.IntegerField(default=0)  # Higher = more important
    due_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    # Checkpoint for resumable long-running operations
    checkpoint_data = models.JSONField(default=dict, blank=True)
    checkpoint_at = models.DateTimeField(null=True, blank=True)

    # Execution tracking
    attempts = models.IntegerField(default=0)
    last_error = models.TextField(blank=True)

    class Meta:
        app_label = "django_agent_runtime"
        db_table = "agent_runtime_persistence_task"
        ordering = ["created_at"]
        verbose_name = "Persistence Task"
        verbose_name_plural = "Persistence Tasks"

    def __str__(self):
        return f"{self.name} ({self.state})"


class Preferences(models.Model):
    """
    User preferences storage for agents.

    Stores configuration and preferences that persist across sessions.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="agent_preferences",
    )
    key = models.CharField(max_length=255, db_index=True)
    value = models.JSONField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = "django_agent_runtime"
        db_table = "agent_runtime_preferences"
        unique_together = [("user", "key")]
        verbose_name = "Agent Preference"
        verbose_name_plural = "Agent Preferences"

    def __str__(self):
        return f"{self.key} ({self.user})"


# =============================================================================
# Knowledge Store Models
# =============================================================================


class FactTypeChoices(models.TextChoices):
    """Fact type choices matching agent_runtime_core.persistence.FactType."""

    USER = "user", "User"
    PROJECT = "project", "Project"
    PREFERENCE = "preference", "Preference"
    CONTEXT = "context", "Context"
    CUSTOM = "custom", "Custom"


class Fact(models.Model):
    """
    A learned fact about user, project, or context.

    Facts can be scoped to:
    - Global (user-level): conversation_id is NULL
    - Conversation-specific: conversation_id is set
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="agent_facts",
    )
    # Optional conversation scope - if set, fact is only visible in that conversation
    conversation_id = models.UUIDField(
        null=True,
        blank=True,
        db_index=True,
        help_text="If set, this fact is scoped to a specific conversation",
    )
    key = models.CharField(max_length=255, db_index=True)
    value = models.JSONField()
    fact_type = models.CharField(
        max_length=20,
        choices=FactTypeChoices.choices,
        default=FactTypeChoices.CUSTOM,
        db_index=True,
    )
    confidence = models.FloatField(default=1.0)  # 0.0 to 1.0
    source = models.CharField(max_length=255, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True, db_index=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = "django_agent_runtime"
        db_table = "agent_runtime_fact"
        # Unique key per user per conversation (or global if conversation_id is NULL)
        unique_together = [("user", "conversation_id", "key")]
        verbose_name = "Fact"
        verbose_name_plural = "Facts"

    def __str__(self):
        return f"{self.key}: {str(self.value)[:50]}"


class Summary(models.Model):
    """
    A summary of a conversation or set of interactions.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="agent_summaries",
    )
    content = models.TextField()
    conversation_id = models.UUIDField(null=True, blank=True, db_index=True)
    conversation_ids = models.JSONField(default=list, blank=True)  # For multi-conversation summaries
    start_time = models.DateTimeField(null=True, blank=True)
    end_time = models.DateTimeField(null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = "django_agent_runtime"
        db_table = "agent_runtime_summary"
        ordering = ["-created_at"]
        verbose_name = "Summary"
        verbose_name_plural = "Summaries"

    def __str__(self):
        return f"Summary: {self.content[:50]}"


class Embedding(models.Model):
    """
    A vector embedding for semantic search.

    Note: For optimal performance with large datasets, consider using
    pgvector extension for PostgreSQL.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="agent_embeddings",
    )
    vector = models.JSONField()  # List of floats; use pgvector for production
    content = models.TextField()  # Original text
    content_type = models.CharField(max_length=50, default="text", db_index=True)
    source_id = models.UUIDField(null=True, blank=True, db_index=True)
    model = models.CharField(max_length=100, blank=True)
    dimensions = models.IntegerField(default=0)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = "django_agent_runtime"
        db_table = "agent_runtime_embedding"
        verbose_name = "Embedding"
        verbose_name_plural = "Embeddings"

    def __str__(self):
        return f"Embedding: {self.content[:50]}"


# =============================================================================
# Audit Store Models
# =============================================================================


class AuditEventTypeChoices(models.TextChoices):
    """Audit event type choices matching agent_runtime_core.persistence.AuditEventType."""

    CONVERSATION_START = "conversation_start", "Conversation Start"
    CONVERSATION_END = "conversation_end", "Conversation End"
    MESSAGE_SENT = "message_sent", "Message Sent"
    MESSAGE_RECEIVED = "message_received", "Message Received"
    TOOL_CALL = "tool_call", "Tool Call"
    TOOL_RESULT = "tool_result", "Tool Result"
    TOOL_ERROR = "tool_error", "Tool Error"
    AGENT_START = "agent_start", "Agent Start"
    AGENT_END = "agent_end", "Agent End"
    AGENT_ERROR = "agent_error", "Agent Error"
    CHECKPOINT_SAVED = "checkpoint_saved", "Checkpoint Saved"
    CHECKPOINT_RESTORED = "checkpoint_restored", "Checkpoint Restored"
    CUSTOM = "custom", "Custom"


class ErrorSeverityChoices(models.TextChoices):
    """Error severity choices matching agent_runtime_core.persistence.ErrorSeverity."""

    DEBUG = "debug", "Debug"
    INFO = "info", "Info"
    WARNING = "warning", "Warning"
    ERROR = "error", "Error"
    CRITICAL = "critical", "Critical"


class AuditEntry(models.Model):
    """
    An audit log entry for tracking interactions.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="agent_audit_entries",
    )
    event_type = models.CharField(
        max_length=30,
        choices=AuditEventTypeChoices.choices,
        db_index=True,
    )
    timestamp = models.DateTimeField(auto_now_add=True, db_index=True)

    # Context
    conversation_id = models.UUIDField(null=True, blank=True, db_index=True)
    run_id = models.UUIDField(null=True, blank=True, db_index=True)
    agent_key = models.CharField(max_length=100, blank=True, db_index=True)

    # Event details
    action = models.CharField(max_length=255, blank=True)
    details = models.JSONField(default=dict, blank=True)

    # Actor information
    actor_type = models.CharField(max_length=20, default="agent")
    actor_id = models.CharField(max_length=255, blank=True)

    # Request/response tracking
    request_id = models.CharField(max_length=255, blank=True)
    parent_event_id = models.UUIDField(null=True, blank=True)

    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        app_label = "django_agent_runtime"
        db_table = "agent_runtime_audit_entry"
        ordering = ["-timestamp"]
        verbose_name = "Audit Entry"
        verbose_name_plural = "Audit Entries"

    def __str__(self):
        return f"{self.event_type}: {self.action}"


class ErrorRecord(models.Model):
    """
    A record of an error for debugging.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="agent_error_records",
    )
    timestamp = models.DateTimeField(auto_now_add=True, db_index=True)
    severity = models.CharField(
        max_length=10,
        choices=ErrorSeverityChoices.choices,
        default=ErrorSeverityChoices.ERROR,
        db_index=True,
    )

    # Error details
    error_type = models.CharField(max_length=255, blank=True)
    message = models.TextField(blank=True)
    stack_trace = models.TextField(blank=True)

    # Context
    conversation_id = models.UUIDField(null=True, blank=True, db_index=True)
    run_id = models.UUIDField(null=True, blank=True, db_index=True)
    agent_key = models.CharField(max_length=100, blank=True, db_index=True)
    context = models.JSONField(default=dict, blank=True)

    # Resolution tracking
    resolved = models.BooleanField(default=False, db_index=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolution_notes = models.TextField(blank=True)

    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        app_label = "django_agent_runtime"
        db_table = "agent_runtime_error_record"
        ordering = ["-timestamp"]
        verbose_name = "Error Record"
        verbose_name_plural = "Error Records"

    def __str__(self):
        return f"{self.severity}: {self.error_type}"


class PerformanceMetric(models.Model):
    """
    A performance metric for monitoring.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="agent_performance_metrics",
    )
    name = models.CharField(max_length=100, db_index=True)
    value = models.FloatField()
    unit = models.CharField(max_length=20, blank=True)
    timestamp = models.DateTimeField(auto_now_add=True, db_index=True)

    # Context
    conversation_id = models.UUIDField(null=True, blank=True, db_index=True)
    run_id = models.UUIDField(null=True, blank=True, db_index=True)
    agent_key = models.CharField(max_length=100, blank=True, db_index=True)

    # Additional dimensions for grouping/filtering
    tags = models.JSONField(default=dict, blank=True)

    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        app_label = "django_agent_runtime"
        db_table = "agent_runtime_performance_metric"
        ordering = ["-timestamp"]
        verbose_name = "Performance Metric"
        verbose_name_plural = "Performance Metrics"

    def __str__(self):
        return f"{self.name}: {self.value} {self.unit}"


# =============================================================================
# Shared Memory Store Models
# =============================================================================


class MemoryScopeChoices(models.TextChoices):
    """Memory scope choices matching agent_runtime_core.privacy.MemoryScope."""

    CONVERSATION = "conversation", "Conversation"
    USER = "user", "User"
    SYSTEM = "system", "System"


class SharedMemory(models.Model):
    """
    Shared memory storage for agents with semantic keys.

    This model supports the SharedMemoryStore interface from agent_runtime_core.
    Memories can be scoped to:
    - CONVERSATION: Scoped to a single conversation (ephemeral)
    - USER: Persists across conversations for a user
    - SYSTEM: Shared across all agents in a system for a user

    Keys use dot-notation for hierarchical organization:
    - user.name → "Chris"
    - user.preferences.theme → "dark"
    - project.name → "Agent Libraries"

    Privacy enforcement:
    - Only authenticated users can have persistent memories
    - Anonymous users get no persistent memory (enforced at store level)
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="shared_memories",
    )

    # Semantic key (dot-notation)
    key = models.CharField(max_length=500, db_index=True)

    # The actual value (JSON-serializable)
    value = models.JSONField()

    # Scope determines visibility
    scope = models.CharField(
        max_length=20,
        choices=MemoryScopeChoices.choices,
        default=MemoryScopeChoices.USER,
        db_index=True,
    )

    # For CONVERSATION scope
    conversation_id = models.UUIDField(null=True, blank=True, db_index=True)

    # For SYSTEM scope (multi-agent systems)
    system_id = models.CharField(max_length=255, blank=True, db_index=True)

    # Source tracking (what created this memory)
    source = models.CharField(
        max_length=255,
        default="agent",
        help_text="What created this memory, e.g., 'agent:triage', 'user:explicit'",
    )

    # Confidence score (0.0-1.0)
    confidence = models.FloatField(default=1.0)

    # Optional expiration
    expires_at = models.DateTimeField(null=True, blank=True, db_index=True)

    # Additional context
    metadata = models.JSONField(default=dict, blank=True)

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = "django_agent_runtime"
        db_table = "agent_runtime_shared_memory"
        # Unique key per user per scope per conversation/system
        unique_together = [("user", "key", "scope", "conversation_id", "system_id")]
        indexes = [
            # For prefix queries (e.g., "user.preferences.*")
            models.Index(fields=["user", "key"]),
            # For scope-based queries
            models.Index(fields=["user", "scope"]),
            # For system-scoped queries
            models.Index(fields=["user", "system_id", "scope"]),
            # For conversation-scoped queries
            models.Index(fields=["user", "conversation_id", "scope"]),
            # For source filtering
            models.Index(fields=["user", "source"]),
            # For expiration cleanup
            models.Index(fields=["expires_at"]),
        ]
        verbose_name = "Shared Memory"
        verbose_name_plural = "Shared Memories"

    def __str__(self):
        return f"{self.key} ({self.scope}): {str(self.value)[:50]}"

    @property
    def is_expired(self) -> bool:
        """Check if this memory has expired."""
        if self.expires_at is None:
            return False
        from django.utils import timezone
        return timezone.now() > self.expires_at
