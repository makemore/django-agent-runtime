"""
Redis-backed event bus using pub/sub and streams.

Real-time streaming with optional database persistence.
Recommended for production with high event volume.
"""

import asyncio
import json
from datetime import datetime, timezone
from typing import AsyncIterator, Optional
from uuid import UUID

from asgiref.sync import sync_to_async
from django.db.models import Max

from django_agent_runtime.models import AgentEvent, AgentRun
from django_agent_runtime.runtime.events.base import EventBus, Event

try:
    import redis.asyncio as aioredis
except ImportError:
    aioredis = None


class RedisEventBus(EventBus):
    """
    Redis-backed event bus implementation.

    Uses Redis Streams for event storage and pub/sub for real-time notifications.
    Optionally persists to database for durability.
    """

    STREAM_PREFIX = "agent_runtime:events:"
    CHANNEL_PREFIX = "agent_runtime:notify:"

    def __init__(
        self,
        redis_url: str,
        persist_to_db: bool = True,
        event_ttl_seconds: int = 3600 * 6,  # 6 hours
        persist_token_deltas: bool = False,
    ):
        """
        Initialize Redis event bus.

        Args:
            redis_url: Redis connection URL
            persist_to_db: Whether to also persist events to database
            event_ttl_seconds: TTL for events in Redis
            persist_token_deltas: Whether to persist token delta events to DB
        """
        if aioredis is None:
            raise ImportError("redis package is required for RedisEventBus")

        self.redis_url = redis_url
        self.persist_to_db = persist_to_db
        self.event_ttl_seconds = event_ttl_seconds
        self.persist_token_deltas = persist_token_deltas
        self._redis: Optional[aioredis.Redis] = None

    async def _get_redis(self) -> "aioredis.Redis":
        """Get or create Redis connection."""
        if self._redis is None:
            self._redis = aioredis.from_url(self.redis_url)
        return self._redis

    def _stream_key(self, run_id: UUID) -> str:
        """Get Redis stream key for a run."""
        return f"{self.STREAM_PREFIX}{run_id}"

    def _channel_key(self, run_id: UUID) -> str:
        """Get Redis pub/sub channel for a run."""
        return f"{self.CHANNEL_PREFIX}{run_id}"

    async def publish(self, event: Event) -> None:
        """Publish event to Redis and optionally database."""
        redis = await self._get_redis()

        # Add to stream
        stream_key = self._stream_key(event.run_id)
        await redis.xadd(
            stream_key,
            {"data": json.dumps(event.to_dict())},
        )

        # Set TTL on stream
        await redis.expire(stream_key, self.event_ttl_seconds)

        # Notify subscribers
        channel_key = self._channel_key(event.run_id)
        await redis.publish(channel_key, str(event.seq))

        # Persist to database if configured
        if self.persist_to_db:
            # Skip token deltas unless configured
            if event.event_type == "assistant.delta" and not self.persist_token_deltas:
                return

            await self._persist_to_db(event)

    @sync_to_async
    def _persist_to_db(self, event: Event) -> None:
        """Persist event to database."""
        AgentEvent.objects.create(
            run_id=event.run_id,
            seq=event.seq,
            event_type=event.event_type,
            payload=event.payload,
        )

    async def subscribe(
        self,
        run_id: UUID,
        from_seq: int = 0,
    ) -> AsyncIterator[Event]:
        """Subscribe to events using pub/sub for notifications."""
        redis = await self._get_redis()
        pubsub = redis.pubsub()
        channel_key = self._channel_key(run_id)

        await pubsub.subscribe(channel_key)

        try:
            # First, get any existing events
            events = await self.get_events(run_id, from_seq=from_seq)
            current_seq = from_seq

            for event in events:
                yield event
                current_seq = event.seq + 1

            # Then listen for new events
            while True:
                # Check if run is complete
                if await self._is_run_complete(run_id):
                    # Get any final events
                    final_events = await self.get_events(run_id, from_seq=current_seq)
                    for event in final_events:
                        yield event
                    break

                # Wait for notification with timeout
                try:
                    message = await asyncio.wait_for(
                        pubsub.get_message(ignore_subscribe_messages=True),
                        timeout=1.0,
                    )
                    if message:
                        # Get new events
                        new_events = await self.get_events(run_id, from_seq=current_seq)
                        for event in new_events:
                            yield event
                            current_seq = event.seq + 1
                except asyncio.TimeoutError:
                    continue

        finally:
            await pubsub.unsubscribe(channel_key)
            await pubsub.close()

    @sync_to_async
    def _is_run_complete(self, run_id: UUID) -> bool:
        """Check if run is in terminal state."""
        try:
            run = AgentRun.objects.get(id=run_id)
            return run.is_terminal
        except AgentRun.DoesNotExist:
            return True

    async def get_events(
        self,
        run_id: UUID,
        from_seq: int = 0,
        to_seq: Optional[int] = None,
    ) -> list[Event]:
        """Get events from Redis stream."""
        redis = await self._get_redis()
        stream_key = self._stream_key(run_id)

        # Read from stream
        messages = await redis.xrange(stream_key)

        events = []
        for msg_id, data in messages:
            event_data = json.loads(data[b"data"].decode())
            event = Event.from_dict(event_data)

            if event.seq < from_seq:
                continue
            if to_seq is not None and event.seq > to_seq:
                continue

            events.append(event)

        return sorted(events, key=lambda e: e.seq)

    async def get_next_seq(self, run_id: UUID) -> int:
        """Get next sequence number from Redis or database."""
        redis = await self._get_redis()
        stream_key = self._stream_key(run_id)

        # Check Redis stream
        messages = await redis.xrevrange(stream_key, count=1)
        if messages:
            msg_id, data = messages[0]
            event_data = json.loads(data[b"data"].decode())
            return event_data["seq"] + 1

        # Fall back to database
        @sync_to_async
        def _get_from_db():
            result = AgentEvent.objects.filter(run_id=run_id).aggregate(
                max_seq=Max("seq")
            )
            max_seq = result["max_seq"]
            # Note: can't use `max_seq or -1` because 0 is falsy!
            if max_seq is None:
                return 0
            return max_seq + 1

        return await _get_from_db()

    async def close(self) -> None:
        """Close Redis connection."""
        if self._redis:
            await self._redis.close()
            self._redis = None
