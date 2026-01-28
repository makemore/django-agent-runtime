"""
Configuration management for django_agent_runtime.

All settings are namespaced under DJANGO_AGENT_RUNTIME in Django settings.
This module provides defaults and validation.

Debug Mode
----------
The framework supports debug/production modes that control exception handling:

- **Debug mode**: Exceptions propagate immediately with full stack traces.
  Useful for development and debugging.
- **Production mode**: Exceptions are caught and handled gracefully with
  retries and user-friendly error messages.

Enable debug mode via:
1. Environment variable: DJANGO_AGENT_RUNTIME_DEBUG=1
2. Django settings: DJANGO_AGENT_RUNTIME = {'SWALLOW_EXCEPTIONS': False}
3. Code: configure(debug=True)
"""

import os
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from django.conf import settings


@dataclass
class AgentRuntimeSettings:
    """
    Settings for the Django Agent Runtime.

    All settings can be overridden via DJANGO_AGENT_RUNTIME dict in Django settings.
    """

    # Queue configuration
    QUEUE_BACKEND: str = "postgres"  # "postgres" | "redis_streams"
    EVENT_BUS_BACKEND: str = "db"  # "redis" | "db"
    REDIS_URL: Optional[str] = None

    # Lease and timeout configuration
    LEASE_TTL_SECONDS: int = 30
    RUN_TIMEOUT_SECONDS: int = 900  # 15 minutes
    STEP_TIMEOUT_SECONDS: int = 120  # 2 minutes per LLM/tool call
    HEARTBEAT_INTERVAL_SECONDS: int = 10

    # Retry configuration
    DEFAULT_MAX_ATTEMPTS: int = 3
    RETRY_BACKOFF_BASE: float = 2.0
    RETRY_BACKOFF_MAX: int = 300  # 5 minutes max backoff

    # Concurrency
    DEFAULT_PROCESSES: int = 1
    DEFAULT_CONCURRENCY: int = 10  # async tasks per process

    # Streaming
    ENABLE_SSE: bool = True
    ENABLE_CHANNELS: bool = False  # Django Channels (optional)
    SSE_KEEPALIVE_SECONDS: int = 15

    # Conversation history
    # When True, agents automatically receive message history from previous runs
    # in the same conversation. This enables multi-turn conversations by default.
    INCLUDE_CONVERSATION_HISTORY: bool = True

    # Maximum number of history messages to include (None = no limit)
    # Useful for limiting context window usage with long conversations
    MAX_HISTORY_MESSAGES: Optional[int] = None

    # Auto-generate conversation titles
    # When True, automatically generates a short title for new conversations
    # based on the first user message and assistant response
    AUTO_GENERATE_CONVERSATION_TITLE: bool = True

    # Model to use for title generation (should be fast/cheap)
    # Good options: "gpt-4o-mini" (OpenAI), "claude-3-haiku-20240307" (Anthropic)
    TITLE_GENERATION_MODEL: str = "gpt-4o-mini"

    # Event persistence
    PERSIST_TOKEN_DELTAS: bool = False  # Token deltas go to Redis only by default
    EVENT_TTL_SECONDS: int = 3600 * 6  # 6 hours in Redis

    # LLM configuration
    MODEL_PROVIDER: str = "openai"  # "openai" | "anthropic" | "litellm" | ...
    LITELLM_ENABLED: bool = False
    DEFAULT_MODEL: str = "gpt-4o"
    
    # API Keys - can be set here or via environment variables
    # Priority: 1) Explicit setting here, 2) Environment variable
    OPENAI_API_KEY: Optional[str] = None
    ANTHROPIC_API_KEY: Optional[str] = None

    # Tracing/observability
    LANGFUSE_ENABLED: bool = False
    LANGFUSE_PUBLIC_KEY: Optional[str] = None
    LANGFUSE_SECRET_KEY: Optional[str] = None
    LANGFUSE_HOST: Optional[str] = None

    # Plugin discovery
    RUNTIME_REGISTRY: list = field(default_factory=list)  # Dotted paths to register functions

    # Authorization hooks (dotted paths to callables)
    AUTHZ_HOOK: Optional[str] = None  # (user, action, run) -> bool
    QUOTA_HOOK: Optional[str] = None  # (user, agent_key) -> bool

    # Completion callback hook (dotted path to callable)
    # Called when a run completes successfully: (run_id: str, output: dict) -> None
    RUN_COMPLETED_HOOK: Optional[str] = None

    # Model customization (for swappable models pattern)
    RUN_MODEL: Optional[str] = None  # e.g., "myapp.MyAgentRun"
    CONVERSATION_MODEL: Optional[str] = None

    # Anonymous session model (optional)
    # Set to your model path, e.g., "accounts.AnonymousSession"
    # Model must have: token field, is_expired property
    ANONYMOUS_SESSION_MODEL: Optional[str] = None

    # File storage configuration
    FILE_STORAGE_BACKEND: str = "local"  # "local" | "s3" | "gcs"
    FILE_STORAGE_ROOT: str = "agent_files"  # Local path or bucket prefix
    FILE_MAX_SIZE_MB: int = 100  # Maximum file size in MB
    FILE_ALLOWED_TYPES: list = field(default_factory=lambda: [
        # Documents
        "application/pdf",
        "application/msword",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/vnd.ms-excel",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "text/plain",
        "text/csv",
        "text/markdown",
        # Images
        "image/jpeg",
        "image/png",
        "image/gif",
        "image/webp",
        "image/svg+xml",
        # Data
        "application/json",
        "application/xml",
        "text/xml",
    ])

    # S3 configuration (when FILE_STORAGE_BACKEND = "s3")
    FILE_S3_BUCKET: Optional[str] = None
    FILE_S3_REGION: Optional[str] = None
    FILE_S3_ACCESS_KEY: Optional[str] = None
    FILE_S3_SECRET_KEY: Optional[str] = None
    FILE_S3_ENDPOINT_URL: Optional[str] = None  # For S3-compatible services

    # GCS configuration (when FILE_STORAGE_BACKEND = "gcs")
    FILE_GCS_BUCKET: Optional[str] = None
    FILE_GCS_PROJECT: Optional[str] = None
    FILE_GCS_CREDENTIALS_PATH: Optional[str] = None

    # File processing options
    FILE_ENABLE_OCR: bool = False
    FILE_OCR_PROVIDER: str = "tesseract"  # "tesseract" | "google_vision" | "aws_textract" | "azure"
    FILE_ENABLE_VISION: bool = False
    FILE_VISION_PROVIDER: str = "openai"  # "openai" | "anthropic" | "gemini"
    FILE_GENERATE_THUMBNAILS: bool = True
    FILE_THUMBNAIL_SIZE: tuple = (200, 200)

    # Event visibility configuration
    # Controls which events are shown to users in the UI
    # Levels: "internal" (never shown), "debug" (shown in debug mode), "user" (always shown)
    EVENT_VISIBILITY: dict = field(default_factory=lambda: {
        # Lifecycle events
        "run.started": "internal",
        "run.heartbeat": "internal",
        "run.succeeded": "user",  # Needed for frontend to know run is complete
        "run.failed": "user",  # Always show errors
        "run.cancelled": "user",
        "run.timed_out": "user",
        # Message events
        "assistant.delta": "user",  # Token streaming
        "assistant.message": "user",  # Complete messages
        # Tool events
        "tool.call": "debug",
        "tool.result": "debug",
        # State events
        "state.checkpoint": "internal",
        # Error events
        "error": "user",  # Runtime errors always shown
    })

    # When True, 'debug' visibility events become visible to UI
    DEBUG_MODE: bool = False

    # Exception handling mode
    # When False (debug mode), exceptions propagate with full stack traces
    # When True (production mode), exceptions are caught and handled gracefully
    SWALLOW_EXCEPTIONS: bool = True

    def __post_init__(self):
        """Validate settings after initialization."""
        valid_queue_backends = {"postgres", "redis_streams"}
        if self.QUEUE_BACKEND not in valid_queue_backends:
            raise ValueError(
                f"QUEUE_BACKEND must be one of {valid_queue_backends}, got {self.QUEUE_BACKEND}"
            )

        valid_event_backends = {"redis", "db"}
        if self.EVENT_BUS_BACKEND not in valid_event_backends:
            raise ValueError(
                f"EVENT_BUS_BACKEND must be one of {valid_event_backends}, got {self.EVENT_BUS_BACKEND}"
            )

        if self.QUEUE_BACKEND == "redis_streams" and not self.REDIS_URL:
            raise ValueError("REDIS_URL is required when using redis_streams queue backend")

        if self.EVENT_BUS_BACKEND == "redis" and not self.REDIS_URL:
            raise ValueError("REDIS_URL is required when using redis event bus backend")
    
    def get_openai_api_key(self) -> Optional[str]:
        """
        Get OpenAI API key with fallback to environment variable.
        
        Priority:
        1. OPENAI_API_KEY in DJANGO_AGENT_RUNTIME settings
        2. OPENAI_API_KEY environment variable
        
        Returns:
            API key string or None if not configured.
        """
        if self.OPENAI_API_KEY:
            return self.OPENAI_API_KEY
        return os.environ.get("OPENAI_API_KEY")
    
    def get_anthropic_api_key(self) -> Optional[str]:
        """
        Get Anthropic API key with fallback to environment variable.
        
        Priority:
        1. ANTHROPIC_API_KEY in DJANGO_AGENT_RUNTIME settings
        2. ANTHROPIC_API_KEY environment variable
        
        Returns:
            API key string or None if not configured.
        """
        if self.ANTHROPIC_API_KEY:
            return self.ANTHROPIC_API_KEY
        return os.environ.get("ANTHROPIC_API_KEY")


def get_settings() -> AgentRuntimeSettings:
    """
    Get the agent runtime settings, merging defaults with user overrides.

    Returns:
        AgentRuntimeSettings instance with all configuration.
    """
    user_settings = getattr(settings, "DJANGO_AGENT_RUNTIME", {})

    # Build settings from defaults + overrides
    return AgentRuntimeSettings(**user_settings)


def get_hook(hook_path: Optional[str]) -> Optional[Callable]:
    """
    Import and return a hook function from a dotted path.

    Args:
        hook_path: Dotted path like "myapp.hooks.check_auth"

    Returns:
        The callable, or None if hook_path is None.
    """
    if not hook_path:
        return None

    from django.utils.module_loading import import_string

    return import_string(hook_path)


# Singleton instance (lazy-loaded)
_settings_instance: Optional[AgentRuntimeSettings] = None


def runtime_settings() -> AgentRuntimeSettings:
    """Get the cached settings instance."""
    global _settings_instance
    if _settings_instance is None:
        _settings_instance = get_settings()
    return _settings_instance


def reset_settings():
    """Reset cached settings (useful for testing)."""
    global _settings_instance
    _settings_instance = None


def get_event_visibility(event_type: str) -> tuple[str, bool]:
    """
    Get the visibility level and ui_visible flag for an event type.

    Args:
        event_type: The event type string (e.g., "run.started", "assistant.message")

    Returns:
        Tuple of (visibility_level, ui_visible)
        - visibility_level: "internal", "debug", or "user"
        - ui_visible: True if the event should be shown in UI
    """
    settings = runtime_settings()
    visibility_map = settings.EVENT_VISIBILITY
    debug_mode = settings.DEBUG_MODE

    # Get visibility level from config, default to "user" for unknown events
    visibility_level = visibility_map.get(event_type, "user")

    # Determine if visible in UI
    if visibility_level == "internal":
        ui_visible = False
    elif visibility_level == "debug":
        ui_visible = debug_mode
    else:  # "user"
        ui_visible = True

    return visibility_level, ui_visible


# =============================================================================
# Debug Mode Configuration
# =============================================================================

def _get_debug_from_env() -> bool:
    """
    Check if debug mode is enabled via environment variable.

    Returns:
        True if DJANGO_AGENT_RUNTIME_DEBUG is set to a truthy value.
    """
    debug_env = os.getenv("DJANGO_AGENT_RUNTIME_DEBUG", "").lower()
    return debug_env in ("1", "true", "yes", "on")


def is_debug() -> bool:
    """
    Check if debug mode is enabled.

    Debug mode is enabled if:
    1. DJANGO_AGENT_RUNTIME_DEBUG environment variable is set to "1", "true", "yes", or "on"
    2. SWALLOW_EXCEPTIONS is False in DJANGO_AGENT_RUNTIME settings

    Returns:
        True if debug mode is enabled.
    """
    # Environment variable takes precedence
    if _get_debug_from_env():
        return True

    # Check settings
    settings_obj = runtime_settings()
    return not settings_obj.SWALLOW_EXCEPTIONS


def should_swallow_exceptions() -> bool:
    """
    Check if exceptions should be swallowed (caught and handled gracefully).

    In production mode (default), exceptions are caught and handled with
    retries and user-friendly error messages.

    In debug mode, exceptions propagate immediately with full stack traces.

    Returns:
        True if exceptions should be swallowed (production mode).
        False if exceptions should propagate (debug mode).
    """
    return not is_debug()


def configure(
    debug: Optional[bool] = None,
    swallow_exceptions: Optional[bool] = None,
) -> None:
    """
    Configure the framework's debug/production mode.

    This function modifies the global settings instance. Changes take effect
    immediately for all subsequent operations.

    Args:
        debug: Enable debug mode. When True, sets swallow_exceptions=False
               unless explicitly overridden.
        swallow_exceptions: Whether to catch exceptions gracefully.
                           If not specified, derived from debug setting.

    Example:
        # Enable debug mode (exceptions propagate)
        configure(debug=True)

        # Production mode (exceptions caught)
        configure(debug=False)

        # Debug mode but still swallow exceptions (unusual but supported)
        configure(debug=True, swallow_exceptions=True)
    """
    global _settings_instance

    # Ensure settings are loaded
    settings_obj = runtime_settings()

    if debug is not None:
        # Auto-adjust swallow_exceptions if not explicitly set
        if swallow_exceptions is None:
            settings_obj.SWALLOW_EXCEPTIONS = not debug
        settings_obj.DEBUG_MODE = debug

    if swallow_exceptions is not None:
        settings_obj.SWALLOW_EXCEPTIONS = swallow_exceptions
