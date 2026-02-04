"""
Django admin configuration for agent runtime models.
"""

from django.contrib import admin
from django.utils.html import format_html

from django_agent_runtime.models import (
    AgentConversation,
    AgentRun,
    AgentEvent,
    AgentCheckpoint,
    AgentDefinition,
    AgentVersion,
    AgentRevision,
    AgentTool,
    AgentKnowledge,
    # Normalized message model
    Message,
    # Dynamic Tool models
    DiscoveredFunction,
    DynamicTool,
    DynamicToolExecution,
    SubAgentTool,
    # Multi-agent system models
    AgentSystem,
    AgentSystemMember,
    AgentSystemVersion,
    AgentSystemSnapshot,
    # Spec document models
    SpecDocument,
    SpecDocumentVersion,
    # Persistence models
    Memory,
    PersistenceConversation,
    PersistenceMessage,
    PersistenceTaskList,
    PersistenceTask,
    Preferences,
    # Knowledge store models
    Fact,
    Summary,
    Embedding,
    # Audit store models
    AuditEntry,
    ErrorRecord,
    PerformanceMetric,
    # Shared memory models
    SharedMemory,
    # Step execution models
    StepCheckpoint,
    StepEvent,
)


class MessageInline(admin.TabularInline):
    """Inline for viewing normalized messages on a conversation."""

    model = Message
    extra = 0
    readonly_fields = ["seq", "role", "content_preview", "run", "created_at"]
    fields = ["seq", "role", "content_preview", "run", "created_at"]
    can_delete = False
    ordering = ["seq"]

    def has_add_permission(self, request, obj=None):
        return False

    def content_preview(self, obj):
        """Show a preview of the message content."""
        content = obj.content
        if content is None:
            return "-"
        if isinstance(content, str):
            return content[:100] + "..." if len(content) > 100 else content
        return str(content)[:100] + "..."
    content_preview.short_description = "Content"


@admin.register(AgentConversation)
class AgentConversationAdmin(admin.ModelAdmin):
    """Admin for AgentConversation."""

    list_display = ["id", "agent_key", "user", "title", "message_count", "storage_mode", "created_at"]
    list_filter = ["agent_key", "created_at"]
    search_fields = ["id", "title", "user__email"]
    readonly_fields = ["id", "created_at", "updated_at"]
    raw_id_fields = ["user"]
    inlines = [MessageInline]

    def message_count(self, obj):
        """Show the number of normalized messages (if using normalized storage)."""
        return obj.messages.count()
    message_count.short_description = "Messages"

    def storage_mode(self, obj):
        """Show the message storage mode for this conversation."""
        return obj.get_message_storage_mode()
    storage_mode.short_description = "Storage Mode"


@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    """Admin for Message - normalized conversation messages."""

    list_display = ["id", "conversation_link", "seq", "role_badge", "content_preview", "run_link", "created_at"]
    list_filter = ["role", "created_at"]
    search_fields = ["conversation__id", "content"]
    readonly_fields = ["id", "conversation", "run", "seq", "created_at"]
    raw_id_fields = ["conversation", "run"]

    def conversation_link(self, obj):
        """Link to the conversation."""
        from django.urls import reverse
        url = reverse("admin:django_agent_runtime_agentconversation_change", args=[obj.conversation_id])
        return format_html('<a href="{}">{}</a>', url, str(obj.conversation_id)[:8])
    conversation_link.short_description = "Conversation"

    def run_link(self, obj):
        """Link to the run that produced this message."""
        if not obj.run_id:
            return "-"
        from django.urls import reverse
        url = reverse("admin:django_agent_runtime_agentrun_change", args=[obj.run_id])
        return format_html('<a href="{}">{}</a>', url, str(obj.run_id)[:8])
    run_link.short_description = "Run"

    def role_badge(self, obj):
        """Show role with color badge."""
        colors = {
            "user": "#28a745",      # green
            "assistant": "#007bff", # blue
            "tool": "#6c757d",      # gray
            "system": "#dc3545",    # red
        }
        color = colors.get(obj.role, "#6c757d")
        return format_html(
            '<span style="background-color: {}; color: white; padding: 2px 8px; border-radius: 4px;">{}</span>',
            color,
            obj.role,
        )
    role_badge.short_description = "Role"

    def content_preview(self, obj):
        """Show a preview of the message content."""
        content = obj.content
        if content is None:
            return "-"
        if isinstance(content, str):
            return content[:80] + "..." if len(content) > 80 else content
        return str(content)[:80] + "..."
    content_preview.short_description = "Content"


class AgentEventInline(admin.TabularInline):
    """Inline for viewing events on a run."""

    model = AgentEvent
    extra = 0
    readonly_fields = ["seq", "event_type", "payload", "timestamp"]
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False


class AgentCheckpointInline(admin.TabularInline):
    """Inline for viewing checkpoints on a run."""

    model = AgentCheckpoint
    extra = 0
    readonly_fields = ["seq", "state", "created_at"]
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(AgentRun)
class AgentRunAdmin(admin.ModelAdmin):
    """Admin for AgentRun."""

    list_display = [
        "id",
        "agent_key",
        "status_badge",
        "attempt",
        "conversation",
        "created_at",
        "duration",
    ]
    list_filter = ["status", "agent_key", "created_at"]
    search_fields = ["id", "agent_key", "idempotency_key"]
    readonly_fields = [
        "id",
        "status",
        "attempt",
        "lease_owner",
        "lease_expires_at",
        "created_at",
        "started_at",
        "finished_at",
        "cancel_requested_at",
    ]
    raw_id_fields = ["conversation"]
    inlines = [AgentEventInline, AgentCheckpointInline]

    fieldsets = (
        (None, {
            "fields": ("id", "agent_key", "conversation", "status")
        }),
        ("Input/Output", {
            "fields": ("input", "output", "error"),
            "classes": ("collapse",),
        }),
        ("Execution", {
            "fields": (
                "attempt",
                "max_attempts",
                "lease_owner",
                "lease_expires_at",
                "cancel_requested_at",
            ),
        }),
        ("Timestamps", {
            "fields": ("created_at", "started_at", "finished_at"),
        }),
        ("Metadata", {
            "fields": ("idempotency_key", "metadata"),
            "classes": ("collapse",),
        }),
    )

    def status_badge(self, obj):
        """Display status as a colored badge."""
        colors = {
            "queued": "#6c757d",
            "running": "#007bff",
            "succeeded": "#28a745",
            "failed": "#dc3545",
            "cancelled": "#ffc107",
            "timed_out": "#fd7e14",
        }
        color = colors.get(obj.status, "#6c757d")
        return format_html(
            '<span style="background-color: {}; color: white; padding: 2px 8px; '
            'border-radius: 4px; font-size: 11px;">{}</span>',
            color,
            obj.status.upper(),
        )
    status_badge.short_description = "Status"

    def duration(self, obj):
        """Calculate run duration."""
        if obj.started_at and obj.finished_at:
            delta = obj.finished_at - obj.started_at
            return f"{delta.total_seconds():.1f}s"
        elif obj.started_at:
            return "Running..."
        return "-"
    duration.short_description = "Duration"


@admin.register(AgentEvent)
class AgentEventAdmin(admin.ModelAdmin):
    """Admin for AgentEvent."""

    list_display = ["id", "run", "seq", "event_type", "timestamp"]
    list_filter = ["event_type", "timestamp"]
    search_fields = ["run__id", "event_type"]
    readonly_fields = ["id", "run", "seq", "event_type", "payload", "timestamp"]
    raw_id_fields = ["run"]


@admin.register(AgentCheckpoint)
class AgentCheckpointAdmin(admin.ModelAdmin):
    """Admin for AgentCheckpoint."""

    list_display = ["id", "run", "seq", "created_at"]
    search_fields = ["run__id"]
    readonly_fields = ["id", "run", "seq", "state", "created_at"]
    raw_id_fields = ["run"]


# =============================================================================
# Agent Definition Admin
# =============================================================================


class AgentVersionInline(admin.TabularInline):
    """Inline for viewing versions on an agent definition."""

    model = AgentVersion
    extra = 0
    fields = ["version", "is_active", "is_draft", "model", "created_at"]
    readonly_fields = ["created_at"]
    show_change_link = True


class AgentToolInline(admin.TabularInline):
    """Inline for viewing tools on an agent definition."""

    model = AgentTool
    fk_name = "agent"  # Specify which FK to use (not subagent)
    extra = 0
    fields = ["name", "tool_type", "description", "is_active", "order"]
    show_change_link = True


class AgentKnowledgeInline(admin.TabularInline):
    """Inline for viewing knowledge sources on an agent definition."""

    model = AgentKnowledge
    extra = 0
    fields = ["name", "knowledge_type", "inclusion_mode", "is_active", "order"]
    show_change_link = True


@admin.register(AgentDefinition)
class AgentDefinitionAdmin(admin.ModelAdmin):
    """Admin for AgentDefinition."""

    list_display = [
        "name",
        "slug",
        "parent",
        "is_active",
        "is_public",
        "is_template",
        "owner",
        "updated_at",
    ]
    list_filter = ["is_active", "is_public", "is_template", "created_at"]
    search_fields = ["name", "slug", "description"]
    readonly_fields = ["id", "created_at", "updated_at"]
    raw_id_fields = ["owner", "parent"]
    prepopulated_fields = {"slug": ("name",)}
    inlines = [AgentVersionInline, AgentToolInline, AgentKnowledgeInline]

    fieldsets = (
        (None, {
            "fields": ("id", "name", "slug", "description", "icon")
        }),
        ("Inheritance", {
            "fields": ("parent",),
        }),
        ("Ownership & Visibility", {
            "fields": ("owner", "is_public", "is_template", "is_active"),
        }),
        ("Timestamps", {
            "fields": ("created_at", "updated_at"),
        }),
    )


@admin.register(AgentVersion)
class AgentVersionAdmin(admin.ModelAdmin):
    """Admin for AgentVersion."""

    list_display = ["agent", "version", "is_active", "is_draft", "model", "created_at"]
    list_filter = ["is_active", "is_draft", "model", "created_at"]
    search_fields = ["agent__name", "agent__slug", "version"]
    readonly_fields = ["id", "created_at", "published_at"]
    raw_id_fields = ["agent"]

    fieldsets = (
        (None, {
            "fields": ("id", "agent", "version", "is_active", "is_draft")
        }),
        ("Configuration", {
            "fields": ("system_prompt", "model", "model_settings", "extra_config"),
        }),
        ("Metadata", {
            "fields": ("notes", "created_at", "published_at"),
        }),
    )


@admin.register(AgentTool)
class AgentToolAdmin(admin.ModelAdmin):
    """Admin for AgentTool."""

    list_display = ["name", "agent", "tool_type", "is_active", "order"]
    list_filter = ["tool_type", "is_active"]
    search_fields = ["name", "agent__name", "description"]
    readonly_fields = ["id"]
    raw_id_fields = ["agent", "subagent"]

    fieldsets = (
        (None, {
            "fields": ("id", "agent", "name", "tool_type", "description")
        }),
        ("Configuration", {
            "fields": ("parameters_schema", "builtin_ref", "subagent", "config"),
        }),
        ("Status", {
            "fields": ("is_active", "order"),
        }),
    )


@admin.register(AgentKnowledge)
class AgentKnowledgeAdmin(admin.ModelAdmin):
    """Admin for AgentKnowledge."""

    list_display = ["name", "agent", "knowledge_type", "inclusion_mode", "is_active", "order"]
    list_filter = ["knowledge_type", "inclusion_mode", "is_active"]
    search_fields = ["name", "agent__name", "content"]
    readonly_fields = ["id", "created_at", "updated_at"]
    raw_id_fields = ["agent"]

    fieldsets = (
        (None, {
            "fields": ("id", "agent", "name", "knowledge_type", "inclusion_mode")
        }),
        ("Content", {
            "fields": ("content", "file", "url", "dynamic_config"),
        }),
        ("Status", {
            "fields": ("is_active", "order"),
        }),
        ("Timestamps", {
            "fields": ("created_at", "updated_at"),
        }),
    )



# =============================================================================
# Agent Revision Admin
# =============================================================================


@admin.register(AgentRevision)
class AgentRevisionAdmin(admin.ModelAdmin):
    """Admin for AgentRevision - immutable snapshots of agent configuration."""

    list_display = ["agent", "revision_number", "created_at", "created_by"]
    list_filter = ["created_at"]
    search_fields = ["agent__name", "agent__slug"]
    readonly_fields = ["id", "agent", "revision_number", "content", "created_at", "created_by"]
    raw_id_fields = ["agent", "created_by"]

    def has_change_permission(self, request, obj=None):
        return False  # Revisions are immutable

    def has_delete_permission(self, request, obj=None):
        # Allow superusers to delete (needed for cascade deletes from AgentDefinition)
        return request.user.is_superuser


# =============================================================================
# Multi-Agent System Admin
# =============================================================================


class AgentSystemMemberInline(admin.TabularInline):
    """Inline for viewing members of a system."""

    model = AgentSystemMember
    extra = 1
    fields = ["agent", "role", "notes", "order"]
    raw_id_fields = ["agent"]


class AgentSystemVersionInline(admin.TabularInline):
    """Inline for viewing versions of a system."""

    model = AgentSystemVersion
    extra = 0
    fields = ["version", "is_active", "is_draft", "created_at"]
    readonly_fields = ["created_at"]
    show_change_link = True


@admin.register(AgentSystem)
class AgentSystemAdmin(admin.ModelAdmin):
    """Admin for AgentSystem - multi-agent systems."""

    list_display = ["name", "slug", "entry_agent", "member_count", "is_active", "updated_at"]
    list_filter = ["is_active", "created_at"]
    search_fields = ["name", "slug", "description"]
    readonly_fields = ["id", "created_at", "updated_at"]
    raw_id_fields = ["owner", "entry_agent"]
    prepopulated_fields = {"slug": ("name",)}
    inlines = [AgentSystemMemberInline, AgentSystemVersionInline]

    fieldsets = (
        (None, {
            "fields": ("id", "name", "slug", "description")
        }),
        ("Configuration", {
            "fields": ("entry_agent",),
        }),
        ("Ownership", {
            "fields": ("owner", "is_active"),
        }),
        ("Timestamps", {
            "fields": ("created_at", "updated_at"),
        }),
    )

    def member_count(self, obj):
        return obj.members.count()
    member_count.short_description = "Members"


@admin.register(AgentSystemMember)
class AgentSystemMemberAdmin(admin.ModelAdmin):
    """Admin for AgentSystemMember."""

    list_display = ["system", "agent", "role", "order"]
    list_filter = ["role", "system"]
    search_fields = ["system__name", "agent__name"]
    raw_id_fields = ["system", "agent"]


class AgentSystemSnapshotInline(admin.TabularInline):
    """Inline for viewing snapshots in a system version."""

    model = AgentSystemSnapshot
    extra = 0
    fields = ["agent", "pinned_revision"]
    raw_id_fields = ["agent", "pinned_revision"]


@admin.register(AgentSystemVersion)
class AgentSystemVersionAdmin(admin.ModelAdmin):
    """Admin for AgentSystemVersion."""

    list_display = ["system", "version", "is_active", "is_draft", "created_at"]
    list_filter = ["is_active", "is_draft", "created_at"]
    search_fields = ["system__name", "version"]
    readonly_fields = ["id", "created_at", "published_at"]
    raw_id_fields = ["system", "created_by"]
    inlines = [AgentSystemSnapshotInline]

    fieldsets = (
        (None, {
            "fields": ("id", "system", "version", "is_active", "is_draft")
        }),
        ("Publishing", {
            "fields": ("notes", "published_at", "created_by"),
        }),
        ("Timestamps", {
            "fields": ("created_at",),
        }),
    )


@admin.register(AgentSystemSnapshot)
class AgentSystemSnapshotAdmin(admin.ModelAdmin):
    """Admin for AgentSystemSnapshot."""

    list_display = ["system_version", "agent", "pinned_revision"]
    search_fields = ["system_version__system__name", "agent__name"]
    raw_id_fields = ["system_version", "agent", "pinned_revision"]


# =============================================================================
# Spec Document Admin
# =============================================================================


class SpecDocumentVersionInline(admin.TabularInline):
    """Inline for viewing versions of a spec document."""

    model = SpecDocumentVersion
    extra = 0
    fields = ["version_number", "title", "change_summary", "created_by", "created_at"]
    readonly_fields = ["version_number", "title", "change_summary", "created_by", "created_at"]
    can_delete = False
    show_change_link = True
    ordering = ["-version_number"]

    def has_add_permission(self, request, obj=None):
        return False


class SpecDocumentChildInline(admin.TabularInline):
    """Inline for viewing child documents."""

    model = SpecDocument
    fk_name = "parent"
    extra = 0
    fields = ["title", "linked_agent", "order", "current_version", "updated_at"]
    readonly_fields = ["current_version", "updated_at"]
    show_change_link = True
    verbose_name = "Child Document"
    verbose_name_plural = "Child Documents"


@admin.register(SpecDocument)
class SpecDocumentAdmin(admin.ModelAdmin):
    """Admin for SpecDocument - specification documents for agents."""

    list_display = [
        "title",
        "linked_agent",
        "parent",
        "owner",
        "current_version",
        "updated_at",
    ]
    list_filter = ["created_at", "updated_at"]
    search_fields = ["title", "content", "linked_agent__name"]
    readonly_fields = ["id", "current_version", "created_at", "updated_at"]
    raw_id_fields = ["parent", "linked_agent", "owner"]
    inlines = [SpecDocumentVersionInline, SpecDocumentChildInline]

    fieldsets = (
        (None, {
            "fields": ("id", "title", "parent", "order")
        }),
        ("Content", {
            "fields": ("content",),
        }),
        ("Agent Link", {
            "fields": ("linked_agent",),
            "description": "Link this document to an agent to sync the spec automatically.",
        }),
        ("Ownership", {
            "fields": ("owner",),
        }),
        ("Metadata", {
            "fields": ("current_version", "created_at", "updated_at"),
        }),
    )


@admin.register(SpecDocumentVersion)
class SpecDocumentVersionAdmin(admin.ModelAdmin):
    """Admin for SpecDocumentVersion - version history of spec documents."""

    list_display = ["document", "version_number", "title", "change_summary", "created_by", "created_at"]
    list_filter = ["created_at"]
    search_fields = ["document__title", "title", "content", "change_summary"]
    readonly_fields = ["id", "document", "version_number", "title", "content", "change_summary", "created_by", "created_at"]
    raw_id_fields = ["document", "created_by"]

    fieldsets = (
        (None, {
            "fields": ("id", "document", "version_number")
        }),
        ("Content Snapshot", {
            "fields": ("title", "content"),
        }),
        ("Metadata", {
            "fields": ("change_summary", "created_by", "created_at"),
        }),
    )

    def has_change_permission(self, request, obj=None):
        return False  # Versions are immutable

    def has_delete_permission(self, request, obj=None):
        # Allow superusers to delete (needed for cascade deletes)
        return request.user.is_superuser


# =============================================================================
# Dynamic Tool Admin
# =============================================================================


@admin.register(DiscoveredFunction)
class DiscoveredFunctionAdmin(admin.ModelAdmin):
    """Admin for DiscoveredFunction - functions discovered from code."""

    list_display = ["name", "module_path", "function_type", "is_selected", "discovered_at"]
    list_filter = ["function_type", "is_selected", "discovered_at"]
    search_fields = ["name", "module_path", "docstring"]
    readonly_fields = ["id", "discovered_at"]


@admin.register(DynamicTool)
class DynamicToolAdmin(admin.ModelAdmin):
    """Admin for DynamicTool - dynamically created tools."""

    list_display = ["name", "agent", "is_active", "created_at"]
    list_filter = ["is_active", "created_at"]
    search_fields = ["name", "description"]
    readonly_fields = ["id", "created_at", "updated_at"]
    raw_id_fields = ["agent"]


@admin.register(DynamicToolExecution)
class DynamicToolExecutionAdmin(admin.ModelAdmin):
    """Admin for DynamicToolExecution - execution logs."""

    list_display = ["tool", "agent_run_id", "status", "started_at", "duration_ms"]
    list_filter = ["status", "started_at"]
    search_fields = ["tool__name"]
    readonly_fields = ["id", "tool", "agent_run_id", "input_arguments", "output_result", "error_message", "started_at", "completed_at"]
    raw_id_fields = ["tool", "executed_by"]


@admin.register(SubAgentTool)
class SubAgentToolAdmin(admin.ModelAdmin):
    """Admin for SubAgentTool - sub-agent tool configurations."""

    list_display = ["name", "parent_agent", "sub_agent", "context_mode", "is_active"]
    list_filter = ["context_mode", "is_active"]
    search_fields = ["name", "parent_agent__name", "sub_agent__name"]
    raw_id_fields = ["parent_agent", "sub_agent"]


# =============================================================================
# Persistence Model Admin
# =============================================================================


@admin.register(Memory)
class MemoryAdmin(admin.ModelAdmin):
    """Admin for Memory - agent memory storage."""

    list_display = ["id", "key", "user", "created_at"]
    list_filter = ["created_at"]
    search_fields = ["key"]
    readonly_fields = ["id", "created_at", "updated_at"]
    raw_id_fields = ["user"]


@admin.register(PersistenceConversation)
class PersistenceConversationAdmin(admin.ModelAdmin):
    """Admin for PersistenceConversation."""

    list_display = ["id", "agent_key", "user", "title", "created_at"]
    list_filter = ["agent_key", "created_at"]
    search_fields = ["title", "agent_key"]
    readonly_fields = ["id", "created_at", "updated_at"]
    raw_id_fields = ["user"]


@admin.register(PersistenceMessage)
class PersistenceMessageAdmin(admin.ModelAdmin):
    """Admin for PersistenceMessage."""

    list_display = ["id", "conversation", "role", "timestamp"]
    list_filter = ["role", "timestamp"]
    search_fields = ["content"]
    readonly_fields = ["id", "timestamp"]
    raw_id_fields = ["conversation"]


@admin.register(PersistenceTaskList)
class PersistenceTaskListAdmin(admin.ModelAdmin):
    """Admin for PersistenceTaskList."""

    list_display = ["id", "name", "user", "run_id", "created_at"]
    list_filter = ["created_at"]
    search_fields = ["name"]
    readonly_fields = ["id", "created_at", "updated_at"]
    raw_id_fields = ["user"]


@admin.register(PersistenceTask)
class PersistenceTaskAdmin(admin.ModelAdmin):
    """Admin for PersistenceTask."""

    list_display = ["id", "task_list", "name", "state", "priority"]
    list_filter = ["state"]
    search_fields = ["name", "description"]
    readonly_fields = ["id", "created_at", "updated_at"]
    raw_id_fields = ["task_list"]


@admin.register(Preferences)
class PreferencesAdmin(admin.ModelAdmin):
    """Admin for Preferences - user/agent preferences."""

    list_display = ["id", "key", "user", "updated_at"]
    list_filter = ["updated_at"]
    search_fields = ["key"]
    readonly_fields = ["id", "created_at", "updated_at"]
    raw_id_fields = ["user"]


# =============================================================================
# Step Execution Admin
# =============================================================================


@admin.register(StepCheckpoint)
class StepCheckpointAdmin(admin.ModelAdmin):
    """Admin for StepCheckpoint - step execution checkpoints."""

    list_display = ["id", "run_id", "checkpoint_key", "status", "started_at"]
    list_filter = ["status", "started_at"]
    search_fields = ["checkpoint_key", "run_id"]
    readonly_fields = ["id", "started_at"]
    raw_id_fields = ["user"]


@admin.register(StepEvent)
class StepEventAdmin(admin.ModelAdmin):
    """Admin for StepEvent - step execution events."""

    list_display = ["id", "checkpoint", "event_type", "timestamp"]
    list_filter = ["event_type", "timestamp"]
    search_fields = ["checkpoint__step_name"]
    readonly_fields = ["id", "timestamp"]
    raw_id_fields = ["checkpoint"]


# =============================================================================
# Knowledge Store Admin
# =============================================================================


@admin.register(Fact)
class FactAdmin(admin.ModelAdmin):
    """Admin for Fact - learned facts about users, projects, or context."""

    list_display = ["key", "fact_type", "user", "conversation_scope", "confidence", "created_at"]
    list_filter = ["fact_type", "created_at"]
    search_fields = ["key", "source"]
    readonly_fields = ["id", "created_at", "updated_at"]
    raw_id_fields = ["user"]

    fieldsets = (
        (None, {
            "fields": ("id", "user", "key", "value", "fact_type")
        }),
        ("Scope", {
            "fields": ("conversation_id",),
            "description": "If conversation_id is set, this fact is scoped to that conversation. Otherwise it's global.",
        }),
        ("Metadata", {
            "fields": ("confidence", "source", "expires_at", "metadata"),
        }),
        ("Timestamps", {
            "fields": ("created_at", "updated_at"),
        }),
    )

    def conversation_scope(self, obj):
        """Display whether fact is global or conversation-scoped."""
        if obj.conversation_id:
            return format_html(
                '<span style="color: #007bff;">Conv: {}</span>',
                str(obj.conversation_id)[:8]
            )
        return format_html('<span style="color: #28a745;">Global</span>')
    conversation_scope.short_description = "Scope"


@admin.register(Summary)
class SummaryAdmin(admin.ModelAdmin):
    """Admin for Summary - conversation summaries."""

    list_display = ["id", "user", "content_preview", "conversation_id", "created_at"]
    list_filter = ["created_at"]
    search_fields = ["content"]
    readonly_fields = ["id", "created_at"]
    raw_id_fields = ["user"]

    fieldsets = (
        (None, {
            "fields": ("id", "user", "content")
        }),
        ("Scope", {
            "fields": ("conversation_id", "conversation_ids", "start_time", "end_time"),
        }),
        ("Metadata", {
            "fields": ("metadata", "created_at"),
        }),
    )

    def content_preview(self, obj):
        """Show truncated content."""
        return obj.content[:80] + "..." if len(obj.content) > 80 else obj.content
    content_preview.short_description = "Content"


@admin.register(Embedding)
class EmbeddingAdmin(admin.ModelAdmin):
    """Admin for Embedding - vector embeddings for semantic search."""

    list_display = ["id", "user", "content_preview", "content_type", "model", "dimensions", "created_at"]
    list_filter = ["content_type", "model", "created_at"]
    search_fields = ["content"]
    readonly_fields = ["id", "created_at"]
    raw_id_fields = ["user"]

    fieldsets = (
        (None, {
            "fields": ("id", "user", "content", "content_type")
        }),
        ("Vector", {
            "fields": ("vector", "model", "dimensions"),
            "classes": ("collapse",),
        }),
        ("References", {
            "fields": ("source_id", "metadata"),
        }),
        ("Timestamps", {
            "fields": ("created_at",),
        }),
    )

    def content_preview(self, obj):
        """Show truncated content."""
        return obj.content[:60] + "..." if len(obj.content) > 60 else obj.content
    content_preview.short_description = "Content"


# =============================================================================
# Audit Store Admin
# =============================================================================


@admin.register(AuditEntry)
class AuditEntryAdmin(admin.ModelAdmin):
    """Admin for AuditEntry - audit log entries."""

    list_display = ["event_type", "action", "user", "agent_key", "actor_type", "timestamp"]
    list_filter = ["event_type", "actor_type", "timestamp"]
    search_fields = ["action", "agent_key", "request_id"]
    readonly_fields = ["id", "timestamp"]
    raw_id_fields = ["user"]

    fieldsets = (
        (None, {
            "fields": ("id", "user", "event_type", "action", "timestamp")
        }),
        ("Context", {
            "fields": ("conversation_id", "run_id", "agent_key"),
        }),
        ("Actor", {
            "fields": ("actor_type", "actor_id"),
        }),
        ("Request Tracking", {
            "fields": ("request_id", "parent_event_id"),
        }),
        ("Details", {
            "fields": ("details", "metadata"),
            "classes": ("collapse",),
        }),
    )


@admin.register(ErrorRecord)
class ErrorRecordAdmin(admin.ModelAdmin):
    """Admin for ErrorRecord - error records for debugging."""

    list_display = ["severity_badge", "error_type", "user", "agent_key", "resolved", "timestamp"]
    list_filter = ["severity", "resolved", "timestamp"]
    search_fields = ["error_type", "message", "agent_key"]
    readonly_fields = ["id", "timestamp"]
    raw_id_fields = ["user"]

    fieldsets = (
        (None, {
            "fields": ("id", "user", "severity", "error_type", "timestamp")
        }),
        ("Error Details", {
            "fields": ("message", "stack_trace"),
        }),
        ("Context", {
            "fields": ("conversation_id", "run_id", "agent_key", "context"),
        }),
        ("Resolution", {
            "fields": ("resolved", "resolved_at", "resolution_notes"),
        }),
        ("Metadata", {
            "fields": ("metadata",),
            "classes": ("collapse",),
        }),
    )

    def severity_badge(self, obj):
        """Display severity as a colored badge."""
        colors = {
            "debug": "#6c757d",
            "info": "#17a2b8",
            "warning": "#ffc107",
            "error": "#dc3545",
            "critical": "#721c24",
        }
        color = colors.get(obj.severity, "#6c757d")
        text_color = "white" if obj.severity in ("error", "critical") else "black"
        return format_html(
            '<span style="background-color: {}; color: {}; padding: 2px 8px; '
            'border-radius: 4px; font-size: 11px;">{}</span>',
            color,
            text_color,
            obj.severity.upper(),
        )
    severity_badge.short_description = "Severity"


@admin.register(PerformanceMetric)
class PerformanceMetricAdmin(admin.ModelAdmin):
    """Admin for PerformanceMetric - performance metrics for monitoring."""

    list_display = ["name", "value", "unit", "user", "agent_key", "timestamp"]
    list_filter = ["name", "timestamp"]
    search_fields = ["name", "agent_key"]
    readonly_fields = ["id", "timestamp"]
    raw_id_fields = ["user"]

    fieldsets = (
        (None, {
            "fields": ("id", "user", "name", "value", "unit", "timestamp")
        }),
        ("Context", {
            "fields": ("conversation_id", "run_id", "agent_key"),
        }),
        ("Tags & Metadata", {
            "fields": ("tags", "metadata"),
            "classes": ("collapse",),
        }),
    )


# =============================================================================
# Shared Memory Admin
# =============================================================================


@admin.register(SharedMemory)
class SharedMemoryAdmin(admin.ModelAdmin):
    """Admin for SharedMemory - shared memory storage with semantic keys."""

    list_display = ["key", "scope_badge", "user", "source", "confidence", "is_expired_display", "updated_at"]
    list_filter = ["scope", "source", "created_at"]
    search_fields = ["key", "source", "system_id"]
    readonly_fields = ["id", "created_at", "updated_at"]
    raw_id_fields = ["user"]

    fieldsets = (
        (None, {
            "fields": ("id", "user", "key", "value")
        }),
        ("Scope", {
            "fields": ("scope", "conversation_id", "system_id"),
            "description": "CONVERSATION: ephemeral, USER: persists across conversations, SYSTEM: shared across agents",
        }),
        ("Metadata", {
            "fields": ("source", "confidence", "expires_at", "metadata"),
        }),
        ("Timestamps", {
            "fields": ("created_at", "updated_at"),
        }),
    )

    def scope_badge(self, obj):
        """Display scope as a colored badge."""
        colors = {
            "conversation": "#6c757d",
            "user": "#007bff",
            "system": "#28a745",
        }
        color = colors.get(obj.scope, "#6c757d")
        return format_html(
            '<span style="background-color: {}; color: white; padding: 2px 8px; '
            'border-radius: 4px; font-size: 11px;">{}</span>',
            color,
            obj.scope.upper(),
        )
    scope_badge.short_description = "Scope"

    def is_expired_display(self, obj):
        """Display whether memory is expired."""
        if obj.expires_at is None:
            return "-"
        if obj.is_expired:
            return format_html('<span style="color: #dc3545;">Expired</span>')
        return format_html('<span style="color: #28a745;">Active</span>')
    is_expired_display.short_description = "Status"
