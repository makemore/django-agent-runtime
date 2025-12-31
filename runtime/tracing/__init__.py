"""
Tracing/observability layer for agent runs.

Provides:
- TraceSink: Abstract interface (from interfaces.py)
- NoopTraceSink: Default no-op implementation
- LangfuseTraceSink: Langfuse integration (optional)
"""

from django_agent_runtime.runtime.interfaces import TraceSink
from django_agent_runtime.runtime.tracing.noop import NoopTraceSink

__all__ = [
    "TraceSink",
    "NoopTraceSink",
    "get_trace_sink",
]


def get_trace_sink() -> TraceSink:
    """
    Factory function to get a trace sink based on settings.

    Returns:
        TraceSink instance (NoopTraceSink if tracing disabled)
    """
    from django_agent_runtime.conf import runtime_settings

    settings = runtime_settings()

    if settings.LANGFUSE_ENABLED:
        try:
            from django_agent_runtime.runtime.tracing.langfuse import LangfuseTraceSink

            return LangfuseTraceSink(
                public_key=settings.LANGFUSE_PUBLIC_KEY,
                secret_key=settings.LANGFUSE_SECRET_KEY,
                host=settings.LANGFUSE_HOST,
            )
        except ImportError:
            import logging

            logging.getLogger(__name__).warning(
                "Langfuse enabled but langfuse package not installed. Using NoopTraceSink."
            )

    return NoopTraceSink()

