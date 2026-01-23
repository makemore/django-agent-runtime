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
    AgentTool,
    AgentKnowledge,
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

