"""
Synchronous event bus implementations.

These are for use in sync contexts like management commands, Celery tasks,
and traditional Django views.
"""

from abc import ABC, abstractmethod
from typing import Iterator, Optional
from uuid import UUID

from django.db.models import Max

from django_agent_runtime.models import AgentEvent, AgentRun
from django_agent_runtime.runtime.events.base import Event


class SyncEventBus(ABC):
    """
    Synchronous interface for event bus implementations.

    Use this in sync contexts like management commands, Celery tasks,
    and traditional Django views.
    """

    @abstractmethod
    def publish(self, event: Event) -> None:
        """Publish an event."""
        ...

    @abstractmethod
    def get_events(
        self,
        run_id: UUID,
        from_seq: int = 0,
        to_seq: Optional[int] = None,
    ) -> list[Event]:
        """Get historical events for a run."""
        ...

    @abstractmethod
    def get_next_seq(self, run_id: UUID) -> int:
        """Get the next sequence number for a run."""
        ...

    def close(self) -> None:
        """Close any connections. Override if needed."""
        pass


class SyncDatabaseEventBus(SyncEventBus):
    """
    Synchronous database-backed event bus implementation.

    All events are persisted to the AgentEvent table.
    """

    def publish(self, event: Event) -> None:
        """Publish event to database."""
        AgentEvent.objects.create(
            run_id=event.run_id,
            seq=event.seq,
            event_type=event.event_type,
            payload=event.payload,
        )

    def get_events(
        self,
        run_id: UUID,
        from_seq: int = 0,
        to_seq: Optional[int] = None,
    ) -> list[Event]:
        """Get events from database."""
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

    def get_next_seq(self, run_id: UUID) -> int:
        """Get next sequence number."""
        result = AgentEvent.objects.filter(run_id=run_id).aggregate(max_seq=Max("seq"))
        max_seq = result["max_seq"]
        # Note: can't use `max_seq or -1` because 0 is falsy!
        if max_seq is None:
            return 0
        return max_seq + 1

    def is_run_complete(self, run_id: UUID) -> bool:
        """Check if run is in terminal state."""
        try:
            run = AgentRun.objects.get(id=run_id)
            return run.is_terminal
        except AgentRun.DoesNotExist:
            return True

    def poll_events(
        self,
        run_id: UUID,
        from_seq: int = 0,
    ) -> Iterator[Event]:
        """
        Poll for events (blocking iterator).

        This is a simple polling implementation for sync contexts.
        For real-time streaming, use the async version with WebSockets.
        """
        import time

        current_seq = from_seq
        poll_interval = 0.5

        while True:
            # Get new events
            events = self.get_events(run_id, from_seq=current_seq)

            for event in events:
                yield event
                current_seq = event.seq + 1

            # Check if run is complete
            if self.is_run_complete(run_id):
                break

            # Poll interval
            time.sleep(poll_interval)

