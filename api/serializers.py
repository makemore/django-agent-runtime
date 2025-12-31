"""
DRF serializers for agent runtime API.
"""

from rest_framework import serializers

from django_agent_runtime.models import AgentRun, AgentConversation, AgentEvent


class AgentConversationSerializer(serializers.ModelSerializer):
    """Serializer for AgentConversation."""

    class Meta:
        model = AgentConversation
        fields = [
            "id",
            "agent_key",
            "title",
            "metadata",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]


class AgentRunSerializer(serializers.ModelSerializer):
    """Serializer for AgentRun."""

    class Meta:
        model = AgentRun
        fields = [
            "id",
            "conversation_id",
            "agent_key",
            "status",
            "input",
            "output",
            "error",
            "attempt",
            "max_attempts",
            "idempotency_key",
            "created_at",
            "started_at",
            "finished_at",
            "metadata",
        ]
        read_only_fields = [
            "id",
            "status",
            "output",
            "error",
            "attempt",
            "created_at",
            "started_at",
            "finished_at",
        ]


class AgentRunCreateSerializer(serializers.Serializer):
    """Serializer for creating a new agent run."""

    agent_key = serializers.CharField(max_length=100)
    conversation_id = serializers.UUIDField(required=False, allow_null=True)
    messages = serializers.ListField(
        child=serializers.DictField(),
        required=True,
        help_text="List of messages in the conversation",
    )
    params = serializers.DictField(
        required=False,
        default=dict,
        help_text="Additional parameters for the agent",
    )
    max_attempts = serializers.IntegerField(
        required=False,
        default=3,
        min_value=1,
        max_value=10,
    )
    idempotency_key = serializers.CharField(
        required=False,
        allow_null=True,
        max_length=255,
    )
    metadata = serializers.DictField(
        required=False,
        default=dict,
    )


class AgentEventSerializer(serializers.ModelSerializer):
    """Serializer for AgentEvent."""

    class Meta:
        model = AgentEvent
        fields = [
            "id",
            "run_id",
            "seq",
            "event_type",
            "payload",
            "timestamp",
        ]
        read_only_fields = fields


class AgentRunDetailSerializer(AgentRunSerializer):
    """Detailed serializer for AgentRun with events."""

    events = AgentEventSerializer(many=True, read_only=True)

    class Meta(AgentRunSerializer.Meta):
        fields = AgentRunSerializer.Meta.fields + ["events"]

