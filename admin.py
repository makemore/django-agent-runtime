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
    # Step execution models
    StepCheckpoint,
    StepEvent,
)


@admin.register(AgentConversation)
class AgentConversationAdmin(admin.ModelAdmin):
    """Admin for AgentConversation."""

    list_display = ["id", "agent_key", "user", "title", "created_at"]
    list_filter = ["agent_key", "created_at"]
    search_fields = ["id", "title", "user__email"]
    readonly_fields = ["id", "created_at", "updated_at"]
    raw_id_fields = ["user"]


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
