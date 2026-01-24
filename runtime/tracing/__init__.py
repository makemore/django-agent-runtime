"""
Django Agent Runtime tracing/observability layer.

This module re-exports tracing components from agent_runtime_core and provides
a Django-specific factory function that uses Django settings.

For new code, consider importing directly from agent_runtime_core.tracing.
"""

# Re-export from agent_runtime_core
from agent_runtime_core.interfaces import TraceSink
from agent_runtime_core.tracing import NoopTraceSink

# Lazy import for optional Langfuse
def _get_langfuse_class():
    from agent_runtime_core.tracing.langfuse import LangfuseTraceSink
    return LangfuseTraceSink

__all__ = [
    "TraceSink",
    "NoopTraceSink",
    "get_trace_sink",
]


def get_trace_sink() -> TraceSink:
    """
    Factory function to get a trace sink based on Django settings.

    Returns:
        TraceSink instance (NoopTraceSink if tracing disabled)
    """
    from django_agent_runtime.conf import runtime_settings

    settings = runtime_settings()

    if getattr(settings, 'LANGFUSE_ENABLED', False):
        try:
            LangfuseTraceSink = _get_langfuse_class()
            return LangfuseTraceSink(
                public_key=getattr(settings, 'LANGFUSE_PUBLIC_KEY', None),
                secret_key=getattr(settings, 'LANGFUSE_SECRET_KEY', None),
                host=getattr(settings, 'LANGFUSE_HOST', None),
            )
        except ImportError:
            import logging
            logging.getLogger(__name__).warning(
                "Langfuse enabled but langfuse package not installed. Using NoopTraceSink."
            )

    return NoopTraceSink()

