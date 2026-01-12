"""
Event bus for streaming agent events to UI.

Provides:
- EventBus: Abstract async interface for event publishing/subscribing
- SyncEventBus: Abstract sync interface for event publishing
- DatabaseEventBus: Async database-backed event bus
- SyncDatabaseEventBus: Sync database-backed event bus
- RedisEventBus: Uses Redis pub/sub for real-time streaming
"""

from django_agent_runtime.runtime.events.base import EventBus, Event
from django_agent_runtime.runtime.events.sync import SyncEventBus, SyncDatabaseEventBus

__all__ = [
    # Async
    "EventBus",
    "Event",
    # Sync
    "SyncEventBus",
    "SyncDatabaseEventBus",
    # Factory functions
    "get_event_bus",
    "get_sync_event_bus",
]


def get_event_bus(backend: str = "db", **kwargs) -> EventBus:
    """
    Factory function to get an async event bus instance.

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


def get_sync_event_bus(backend: str = "db", **kwargs) -> SyncEventBus:
    """
    Factory function to get a synchronous event bus instance.

    Args:
        backend: "db" (only db supported for sync)
        **kwargs: Backend-specific configuration

    Returns:
        SyncEventBus instance
    """
    if backend == "db":
        return SyncDatabaseEventBus(**kwargs)
    else:
        raise ValueError(f"Unknown or unsupported sync event bus backend: {backend}")
