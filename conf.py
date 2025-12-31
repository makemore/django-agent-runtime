"""
Configuration management for django_agent_runtime.

All settings are namespaced under DJANGO_AGENT_RUNTIME in Django settings.
This module provides defaults and validation.
"""

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

    # Event persistence
    PERSIST_TOKEN_DELTAS: bool = False  # Token deltas go to Redis only by default
    EVENT_TTL_SECONDS: int = 3600 * 6  # 6 hours in Redis

    # LLM configuration
    MODEL_PROVIDER: str = "openai"  # "openai" | "anthropic" | "litellm" | ...
    LITELLM_ENABLED: bool = False
    DEFAULT_MODEL: str = "gpt-4o"

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

    # Model customization (for swappable models pattern)
    RUN_MODEL: Optional[str] = None  # e.g., "myapp.MyAgentRun"
    CONVERSATION_MODEL: Optional[str] = None

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

