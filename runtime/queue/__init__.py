"""
Queue adapters for distributing agent runs to workers.

Provides:
- RunQueue: Abstract interface for queue implementations
- PostgresQueue: Database-backed queue using SELECT FOR UPDATE SKIP LOCKED
- RedisStreamsQueue: Redis Streams-backed queue with consumer groups
"""

from django_agent_runtime.runtime.queue.base import RunQueue, QueuedRun
from django_agent_runtime.runtime.queue.postgres import PostgresQueue

__all__ = [
    "RunQueue",
    "QueuedRun",
    "PostgresQueue",
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

