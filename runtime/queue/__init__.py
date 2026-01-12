"""
Queue adapters for distributing agent runs to workers.

Provides:
- RunQueue: Abstract async interface for queue implementations
- SyncRunQueue: Abstract sync interface for queue implementations
- PostgresQueue: Async database-backed queue using SELECT FOR UPDATE SKIP LOCKED
- SyncPostgresQueue: Sync database-backed queue
- RedisStreamsQueue: Redis Streams-backed queue with consumer groups
"""

from typing import Union

from django_agent_runtime.runtime.queue.base import RunQueue, QueuedRun
from django_agent_runtime.runtime.queue.postgres import PostgresQueue
from django_agent_runtime.runtime.queue.sync import SyncRunQueue, SyncPostgresQueue

__all__ = [
    # Async
    "RunQueue",
    "QueuedRun",
    "PostgresQueue",
    # Sync
    "SyncRunQueue",
    "SyncPostgresQueue",
    # Factory functions
    "get_queue",
    "get_sync_queue",
]

# Conditional import for Redis
try:
    from django_agent_runtime.runtime.queue.redis_streams import RedisStreamsQueue

    __all__.append("RedisStreamsQueue")
except ImportError:
    pass  # Redis not installed


def get_queue(backend: str = "postgres", **kwargs) -> RunQueue:
    """
    Factory function to get a queue instance.

    Args:
        backend: "postgres" or "redis_streams"
        **kwargs: Backend-specific configuration

    Returns:
        RunQueue instance
    """
    if backend == "postgres":
        return PostgresQueue(**kwargs)
    elif backend == "redis_streams":
        from django_agent_runtime.runtime.queue.redis_streams import RedisStreamsQueue

        return RedisStreamsQueue(**kwargs)
    else:
        raise ValueError(f"Unknown queue backend: {backend}")


def get_sync_queue(backend: str = "postgres", **kwargs) -> SyncRunQueue:
    """
    Factory function to get a synchronous queue instance.

    Args:
        backend: "postgres" (only postgres supported for sync)
        **kwargs: Backend-specific configuration

    Returns:
        SyncRunQueue instance
    """
    if backend == "postgres":
        return SyncPostgresQueue(**kwargs)
    else:
        raise ValueError(f"Unknown or unsupported sync queue backend: {backend}")
