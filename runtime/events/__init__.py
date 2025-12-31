"""
Event bus for streaming agent events to UI.

Provides:
- EventBus: Abstract interface for event publishing/subscribing
- DatabaseEventBus: Stores events in database (baseline)
- RedisEventBus: Uses Redis pub/sub for real-time streaming
"""

from django_agent_runtime.runtime.events.base import EventBus, Event

__all__ = [
    "EventBus",
    "Event",
]


def get_event_bus(backend: str = "db", **kwargs) -> EventBus:
    """
    Factory function to get an event bus instance.

    Args:
        backend: "db" or "redis"
        **kwargs: Backend-specific configuration

    Returns:
        EventBus instance
    """
    if backend == "db":
        from django_agent_runtime.runtime.events.db import DatabaseEventBus

        return DatabaseEventBus(**kwargs)
    elif backend == "redis":
        from django_agent_runtime.runtime.events.redis import RedisEventBus

        return RedisEventBus(**kwargs)
    else:
        raise ValueError(f"Unknown event bus backend: {backend}")

