"""
Abstract base class for queue implementations.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Optional
from uuid import UUID


@dataclass
class QueuedRun:
    """
    A run claimed from the queue.

    Contains the run ID and metadata needed for execution.
    """

    run_id: UUID
    agent_key: str
    attempt: int
    lease_expires_at: datetime
    input: dict
    metadata: dict


class RunQueue(ABC):
    """
    Abstract interface for run queue implementations.

    Queues handle:
    - Claiming runs with leases
    - Extending leases (heartbeats)
    - Releasing runs (success/failure)
    - Recovering expired leases
    """

    @abstractmethod
    async def claim(
        self,
        worker_id: str,
        agent_keys: Optional[list[str]] = None,
        batch_size: int = 1,
    ) -> list[QueuedRun]:
        """
        Claim runs from the queue.

        Args:
            worker_id: Unique identifier for this worker
            agent_keys: Optional filter for specific agent types
            batch_size: Maximum number of runs to claim

        Returns:
            List of claimed runs (may be empty)
        """
        ...

    @abstractmethod
    async def extend_lease(self, run_id: UUID, worker_id: str, seconds: int) -> bool:
        """
        Extend the lease on a run (heartbeat).

        Args:
            run_id: Run to extend
            worker_id: Must match the current lease owner
            seconds: Seconds to extend the lease

        Returns:
            True if extended, False if lease was lost
        """
        ...

    @abstractmethod
    async def release(
        self,
        run_id: UUID,
        worker_id: str,
        success: bool,
        output: Optional[dict] = None,
        error: Optional[dict] = None,
    ) -> None:
        """
        Release a run after completion.

        Args:
            run_id: Run to release
            worker_id: Must match the current lease owner
            success: Whether the run succeeded
            output: Final output (if success)
            error: Error info (if failure)
        """
        ...

    @abstractmethod
    async def requeue_for_retry(
        self,
        run_id: UUID,
        worker_id: str,
        error: dict,
        delay_seconds: int = 0,
    ) -> bool:
        """
        Requeue a run for retry.

        Args:
            run_id: Run to requeue
            worker_id: Must match the current lease owner
            error: Error information
            delay_seconds: Delay before the run becomes available

        Returns:
            True if requeued, False if max attempts reached
        """
        ...

    @abstractmethod
    async def cancel(self, run_id: UUID) -> bool:
        """
        Mark a run for cancellation.

        Args:
            run_id: Run to cancel

        Returns:
            True if cancellation was requested
        """
        ...

    @abstractmethod
    async def is_cancelled(self, run_id: UUID) -> bool:
        """
        Check if a run has been cancelled.

        Args:
            run_id: Run to check

        Returns:
            True if cancellation was requested
        """
        ...

    @abstractmethod
    async def recover_expired_leases(self) -> int:
        """
        Recover runs with expired leases.

        Called periodically to handle worker failures.

        Returns:
            Number of runs recovered
        """
        ...

    async def close(self) -> None:
        """Close any connections. Override if needed."""
        pass

