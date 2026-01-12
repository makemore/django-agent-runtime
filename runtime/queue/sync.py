"""
Synchronous queue implementations.

These are for use in sync contexts like management commands, Celery tasks,
and traditional Django views.
"""

from abc import ABC, abstractmethod
from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import UUID

from django.db import transaction
from django.db.models import F, Q

from django_agent_runtime.models import AgentRun
from django_agent_runtime.models.base import RunStatus
from django_agent_runtime.runtime.queue.base import QueuedRun


class SyncRunQueue(ABC):
    """
    Synchronous interface for run queue implementations.

    Use this in sync contexts like management commands, Celery tasks,
    and traditional Django views.
    """

    @abstractmethod
    def claim(
        self,
        worker_id: str,
        agent_keys: Optional[list[str]] = None,
        batch_size: int = 1,
    ) -> list[QueuedRun]:
        """Claim runs from the queue."""
        ...

    @abstractmethod
    def extend_lease(self, run_id: UUID, worker_id: str, seconds: int) -> bool:
        """Extend the lease on a run (heartbeat)."""
        ...

    @abstractmethod
    def release(
        self,
        run_id: UUID,
        worker_id: str,
        success: bool,
        output: Optional[dict] = None,
        error: Optional[dict] = None,
    ) -> None:
        """Release a run after completion."""
        ...

    @abstractmethod
    def requeue_for_retry(
        self,
        run_id: UUID,
        worker_id: str,
        error: dict,
        delay_seconds: int = 0,
    ) -> bool:
        """Requeue a run for retry."""
        ...

    @abstractmethod
    def cancel(self, run_id: UUID) -> bool:
        """Mark a run for cancellation."""
        ...

    @abstractmethod
    def is_cancelled(self, run_id: UUID) -> bool:
        """Check if a run has been cancelled."""
        ...

    @abstractmethod
    def recover_expired_leases(self) -> int:
        """Recover runs with expired leases."""
        ...

    def close(self) -> None:
        """Close any connections. Override if needed."""
        pass


class SyncPostgresQueue(SyncRunQueue):
    """
    Synchronous PostgreSQL-backed queue implementation.

    Uses SELECT FOR UPDATE SKIP LOCKED for atomic claiming.
    """

    def __init__(self, lease_ttl_seconds: int = 30):
        self.lease_ttl_seconds = lease_ttl_seconds

    def claim(
        self,
        worker_id: str,
        agent_keys: Optional[list[str]] = None,
        batch_size: int = 1,
    ) -> list[QueuedRun]:
        """Claim runs using SELECT FOR UPDATE SKIP LOCKED."""
        now = datetime.now(timezone.utc)
        lease_expires = now + timedelta(seconds=self.lease_ttl_seconds)

        with transaction.atomic():
            # Build query for claimable runs
            query = Q(status=RunStatus.QUEUED) | Q(
                status=RunStatus.RUNNING,
                lease_expires_at__lt=now,  # Expired lease
            )

            queryset = AgentRun.objects.filter(query)

            if agent_keys:
                queryset = queryset.filter(agent_key__in=agent_keys)

            # SELECT FOR UPDATE SKIP LOCKED
            runs = list(queryset.select_for_update(skip_locked=True)[:batch_size])

            claimed = []
            for run in runs:
                # Update lease
                run.status = RunStatus.RUNNING
                run.lease_owner = worker_id
                run.lease_expires_at = lease_expires
                if run.started_at is None:
                    run.started_at = now
                run.save(
                    update_fields=[
                        "status",
                        "lease_owner",
                        "lease_expires_at",
                        "started_at",
                    ]
                )

                claimed.append(
                    QueuedRun(
                        run_id=run.id,
                        agent_key=run.agent_key,
                        attempt=run.attempt,
                        lease_expires_at=lease_expires,
                        input=run.input,
                        metadata=run.metadata,
                    )
                )

            return claimed

    def extend_lease(self, run_id: UUID, worker_id: str, seconds: int) -> bool:
        """Extend lease if we still own it."""
        now = datetime.now(timezone.utc)
        new_expires = now + timedelta(seconds=seconds)

        updated = AgentRun.objects.filter(
            id=run_id,
            lease_owner=worker_id,
            status=RunStatus.RUNNING,
        ).update(lease_expires_at=new_expires)

        return updated > 0

    def release(
        self,
        run_id: UUID,
        worker_id: str,
        success: bool,
        output: Optional[dict] = None,
        error: Optional[dict] = None,
    ) -> None:
        """Release run after completion."""
        now = datetime.now(timezone.utc)

        updates = {
            "status": RunStatus.SUCCEEDED if success else RunStatus.FAILED,
            "finished_at": now,
            "lease_owner": "",
            "lease_expires_at": None,
        }

        if output:
            updates["output"] = output
        if error:
            updates["error"] = error

        AgentRun.objects.filter(
            id=run_id,
            lease_owner=worker_id,
        ).update(**updates)

    def requeue_for_retry(
        self,
        run_id: UUID,
        worker_id: str,
        error: dict,
        delay_seconds: int = 0,
    ) -> bool:
        """Requeue for retry if attempts remain."""
        with transaction.atomic():
            try:
                run = AgentRun.objects.select_for_update().get(
                    id=run_id, lease_owner=worker_id
                )
            except AgentRun.DoesNotExist:
                return False

            if run.attempt >= run.max_attempts:
                # Max attempts reached
                run.status = RunStatus.FAILED
                run.error = error
                run.finished_at = datetime.now(timezone.utc)
                run.lease_owner = ""
                run.lease_expires_at = None
                run.save()
                return False

            # Requeue with incremented attempt
            run.status = RunStatus.QUEUED
            run.attempt = F("attempt") + 1
            run.error = error
            run.lease_owner = ""
            run.lease_expires_at = None
            run.save()
            return True

    def cancel(self, run_id: UUID) -> bool:
        """Mark run for cancellation."""
        now = datetime.now(timezone.utc)
        updated = AgentRun.objects.filter(
            id=run_id,
            status__in=[RunStatus.QUEUED, RunStatus.RUNNING],
        ).update(cancel_requested_at=now)
        return updated > 0

    def is_cancelled(self, run_id: UUID) -> bool:
        """Check if cancellation was requested."""
        try:
            run = AgentRun.objects.get(id=run_id)
            return run.cancel_requested_at is not None
        except AgentRun.DoesNotExist:
            return False

    def recover_expired_leases(self) -> int:
        """Recover runs with expired leases."""
        now = datetime.now(timezone.utc)

        # Find runs with expired leases
        expired = AgentRun.objects.filter(
            status=RunStatus.RUNNING,
            lease_expires_at__lt=now,
        )

        count = 0
        for run in expired:
            if run.attempt >= run.max_attempts:
                # Mark as timed out
                run.status = RunStatus.TIMED_OUT
                run.finished_at = now
                run.error = {
                    "type": "LeaseExpired",
                    "message": "Worker lease expired without completion",
                    "retriable": False,
                }
            else:
                # Requeue for retry
                run.status = RunStatus.QUEUED
                run.attempt += 1

            run.lease_owner = ""
            run.lease_expires_at = None
            run.save()
            count += 1

        return count

