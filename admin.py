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

