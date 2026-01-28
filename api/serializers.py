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


class AgentConversationDetailSerializer(AgentConversationSerializer):
    """Detailed serializer for AgentConversation with messages."""

    messages = serializers.SerializerMethodField()
    total_messages = serializers.SerializerMethodField()
    has_more = serializers.SerializerMethodField()

    class Meta(AgentConversationSerializer.Meta):
        fields = AgentConversationSerializer.Meta.fields + ["messages", "total_messages", "has_more"]

    def get_messages(self, obj):
        """Get message history from the conversation with optional pagination."""
        request = self.context.get("request")
        all_messages = obj.get_message_history(include_failed_runs=False)

        # Check for pagination params
        if request:
            limit = request.query_params.get("limit")
            offset = request.query_params.get("offset")

            if limit is not None:
                limit = int(limit)
                offset = int(offset) if offset else 0

                # Return messages from offset, limited to limit count
                # Messages are in chronological order, so for "last N" we slice from end
                if offset == 0 and limit > 0:
                    # Initial load: get last N messages
                    return all_messages[-limit:] if len(all_messages) > limit else all_messages
                else:
                    # Loading more: get messages before the current offset from the end
                    # offset=10 means we already have the last 10, so get the 10 before that
                    end_idx = len(all_messages) - offset
                    start_idx = max(0, end_idx - limit)
                    return all_messages[start_idx:end_idx]

        return all_messages

    def get_total_messages(self, obj):
        """Get total count of messages in the conversation."""
        return len(obj.get_message_history(include_failed_runs=False))

    def get_has_more(self, obj):
        """Check if there are more messages to load."""
        request = self.context.get("request")
        if request:
            limit = request.query_params.get("limit")
            offset = request.query_params.get("offset", 0)

            if limit is not None:
                total = len(obj.get_message_history(include_failed_runs=False))
                loaded = int(offset) + int(limit)
                return loaded < total
        return False


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


# =============================================================================
# File Serializers
# =============================================================================

from django_agent_runtime.models import AgentFile


class AgentFileSerializer(serializers.ModelSerializer):
    """Serializer for AgentFile."""

    download_url = serializers.SerializerMethodField()
    thumbnail_url = serializers.SerializerMethodField()

    class Meta:
        model = AgentFile
        fields = [
            "id",
            "conversation_id",
            "original_filename",
            "content_type",
            "size_bytes",
            "storage_backend",
            "processing_status",
            "extracted_text",
            "ocr_provider",
            "vision_provider",
            "vision_description",
            "processing_metadata",
            "error_message",
            "created_at",
            "updated_at",
            "processed_at",
            "download_url",
            "thumbnail_url",
        ]
        read_only_fields = [
            "id",
            "storage_backend",
            "processing_status",
            "extracted_text",
            "ocr_provider",
            "vision_provider",
            "vision_description",
            "processing_metadata",
            "error_message",
            "created_at",
            "updated_at",
            "processed_at",
            "download_url",
            "thumbnail_url",
        ]

    def get_download_url(self, obj):
        """Get the download URL for the file."""
        request = self.context.get("request")
        if request and obj.storage_path:
            return request.build_absolute_uri(f"/api/files/{obj.id}/download/")
        return None

    def get_thumbnail_url(self, obj):
        """Get the thumbnail URL if available."""
        request = self.context.get("request")
        if request and obj.thumbnail_path:
            return request.build_absolute_uri(f"/api/files/{obj.id}/thumbnail/")
        return None


class AgentFileUploadSerializer(serializers.Serializer):
    """Serializer for file upload requests."""

    file = serializers.FileField(
        required=True,
        help_text="The file to upload",
    )
    conversation_id = serializers.UUIDField(
        required=False,
        allow_null=True,
        help_text="Optional conversation to associate the file with",
    )
    process = serializers.BooleanField(
        required=False,
        default=True,
        help_text="Whether to process the file (extract text, OCR, etc.)",
    )
    ocr_provider = serializers.ChoiceField(
        required=False,
        allow_null=True,
        choices=["tesseract", "google_vision", "aws_textract", "azure_document"],
        help_text="OCR provider to use for image/PDF text extraction",
    )
    vision_provider = serializers.ChoiceField(
        required=False,
        allow_null=True,
        choices=["openai", "anthropic", "gemini"],
        help_text="Vision AI provider to use for image understanding",
    )
    vision_prompt = serializers.CharField(
        required=False,
        allow_null=True,
        allow_blank=True,
        help_text="Custom prompt for vision AI analysis",
    )

    def validate_file(self, value):
        """Validate file size and type."""
        from django_agent_runtime.conf import runtime_settings

        settings = runtime_settings()
        max_size = settings.FILE_MAX_SIZE_BYTES

        if value.size > max_size:
            raise serializers.ValidationError(
                f"File size ({value.size} bytes) exceeds maximum allowed size ({max_size} bytes)"
            )

        # Check allowed types if configured
        if settings.FILE_ALLOWED_TYPES:
            content_type = value.content_type
            if content_type not in settings.FILE_ALLOWED_TYPES:
                raise serializers.ValidationError(
                    f"File type '{content_type}' is not allowed. "
                    f"Allowed types: {', '.join(settings.FILE_ALLOWED_TYPES)}"
                )

        return value
