"""
Database-backed event bus.

Stores all events in the database. Simple but higher latency for streaming.
Good for development and low-volume production.
"""

import asyncio
from datetime import datetime, timezone
from typing import AsyncIterator, Optional
from uuid import UUID

from asgiref.sync import sync_to_async
from django.db.models import Max

from django_agent_runtime.models import AgentEvent, AgentRun
from django_agent_runtime.runtime.events.base import EventBus, Event


class DatabaseEventBus(EventBus):
    """
    Database-backed event bus implementation.

    All events are persisted to the AgentEvent table.
    Streaming is implemented via polling.
    """

    def __init__(self, poll_interval: float = 0.5):
        """
        Initialize database event bus.

        Args:
            poll_interval: Seconds between polls when streaming
        """
        self.poll_interval = poll_interval

    async def publish(self, event: Event) -> None:
        """Publish event to database."""

        @sync_to_async
        def _publish():
            AgentEvent.objects.create(
                run_id=event.run_id,
                seq=event.seq,
                event_type=event.event_type,
                payload=event.payload,
            )

        await _publish()

    async def subscribe(
        self,
        run_id: UUID,
        from_seq: int = 0,
    ) -> AsyncIterator[Event]:
        """Subscribe to events via polling."""
        current_seq = from_seq

        while True:
            # Get new events
            events = await self.get_events(run_id, from_seq=current_seq)

            for event in events:
                yield event
                current_seq = event.seq + 1

            # Check if run is complete
            if await self._is_run_complete(run_id):
                break

            # Poll interval
            await asyncio.sleep(self.poll_interval)

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
        """Get events from database."""

        @sync_to_async
        def _get():
            queryset = AgentEvent.objects.filter(
                run_id=run_id,
                seq__gte=from_seq,
            )

            if to_seq is not None:
                queryset = queryset.filter(seq__lte=to_seq)

            return [
                Event(
                    run_id=e.run_id,
                    seq=e.seq,
                    event_type=e.event_type,
                    payload=e.payload,
                    timestamp=e.timestamp,
                )
                for e in queryset.order_by("seq")
            ]

        return await _get()

    async def get_next_seq(self, run_id: UUID) -> int:
        """Get next sequence number."""

        @sync_to_async
        def _get_next():
            result = AgentEvent.objects.filter(run_id=run_id).aggregate(
                max_seq=Max("seq")
            )
            max_seq = result["max_seq"]
            # Note: can't use `max_seq or -1` because 0 is falsy!
            if max_seq is None:
                return 0
            return max_seq + 1

        return await _get_next()

