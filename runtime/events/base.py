"""
Abstract base class for event bus implementations.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import AsyncIterator, Optional
from uuid import UUID


@dataclass
class Event:
    """
    An event emitted by an agent runtime.

    Events are the communication channel between workers and UI.
    """

    run_id: UUID
    seq: int
    event_type: str
    payload: dict = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.utcnow)

    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        return {
            "run_id": str(self.run_id),
            "seq": self.seq,
            "type": self.event_type,
            "payload": self.payload,
            "ts": self.timestamp.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Event":
        """Create from dictionary."""
        return cls(
            run_id=UUID(data["run_id"]),
            seq=data["seq"],
            event_type=data["type"],
            payload=data.get("payload", {}),
            timestamp=datetime.fromisoformat(data["ts"]),
        )


class EventBus(ABC):
    """
    Abstract interface for event bus implementations.

    Event buses handle:
    - Publishing events from workers
    - Subscribing to events for streaming to UI
    - Persisting events for replay
    """

    @abstractmethod
    async def publish(self, event: Event) -> None:
        """
        Publish an event.

        Args:
            event: Event to publish
        """
        ...

    @abstractmethod
    async def subscribe(
        self,
        run_id: UUID,
        from_seq: int = 0,
    ) -> AsyncIterator[Event]:
        """
        Subscribe to events for a run.

        Args:
            run_id: Run to subscribe to
            from_seq: Start from this sequence number (for replay)

        Yields:
            Events as they arrive
        """
        ...

    @abstractmethod
    async def get_events(
        self,
        run_id: UUID,
        from_seq: int = 0,
        to_seq: Optional[int] = None,
    ) -> list[Event]:
        """
        Get historical events for a run.

        Args:
            run_id: Run to get events for
            from_seq: Start sequence (inclusive)
            to_seq: End sequence (inclusive), None for all

        Returns:
            List of events
        """
        ...

    @abstractmethod
    async def get_next_seq(self, run_id: UUID) -> int:
        """
        Get the next sequence number for a run.

        Args:
            run_id: Run to get sequence for

        Returns:
            Next sequence number (0 if no events)
        """
        ...

    async def close(self) -> None:
        """Close any connections. Override if needed."""
        pass

