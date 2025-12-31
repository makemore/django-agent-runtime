"""
Redis Streams-backed queue with consumer groups.

Higher throughput than Postgres queue, recommended for production.
Database remains authoritative - Redis is used for distribution only.
"""

import json
from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import UUID

from asgiref.sync import sync_to_async
from django.db import transaction

from django_agent_runtime.models import AgentRun
from django_agent_runtime.models.base import RunStatus
from django_agent_runtime.runtime.queue.base import RunQueue, QueuedRun

try:
    import redis.asyncio as aioredis
except ImportError:
    aioredis = None


class RedisStreamsQueue(RunQueue):
    """
    Redis Streams-backed queue implementation.

    Uses consumer groups for distributed processing.
    Database is still the source of truth - Redis handles distribution.
    """

    STREAM_KEY = "agent_runtime:runs"
    GROUP_NAME = "agent_workers"

    def __init__(
        self,
        redis_url: str,
        lease_ttl_seconds: int = 30,
        stream_key: Optional[str] = None,
        group_name: Optional[str] = None,
    ):
        if aioredis is None:
            raise ImportError("redis package is required for RedisStreamsQueue")

        self.redis_url = redis_url
        self.lease_ttl_seconds = lease_ttl_seconds
        self.stream_key = stream_key or self.STREAM_KEY
        self.group_name = group_name or self.GROUP_NAME
        self._redis: Optional[aioredis.Redis] = None

    async def _get_redis(self) -> "aioredis.Redis":
        """Get or create Redis connection."""
        if self._redis is None:
            self._redis = aioredis.from_url(self.redis_url)
            # Ensure consumer group exists
            try:
                await self._redis.xgroup_create(
                    self.stream_key, self.group_name, id="0", mkstream=True
                )
            except aioredis.ResponseError as e:
                if "BUSYGROUP" not in str(e):
                    raise
        return self._redis

    async def enqueue(self, run_id: UUID, agent_key: str) -> None:
        """
        Add a run to the stream.

        Called when a new run is created.
        """
        redis = await self._get_redis()
        await redis.xadd(
            self.stream_key,
            {"run_id": str(run_id), "agent_key": agent_key},
        )

    async def claim(
        self,
        worker_id: str,
        agent_keys: Optional[list[str]] = None,
        batch_size: int = 1,
    ) -> list[QueuedRun]:
        """Claim runs from the stream using consumer groups."""
        redis = await self._get_redis()
        now = datetime.now(timezone.utc)
        lease_expires = now + timedelta(seconds=self.lease_ttl_seconds)

        # Read from consumer group
        messages = await redis.xreadgroup(
            self.group_name,
            worker_id,
            {self.stream_key: ">"},
            count=batch_size,
            block=1000,  # 1 second block
        )

        if not messages:
            return []

        claimed = []
        for stream_name, stream_messages in messages:
            for msg_id, data in stream_messages:
                run_id = UUID(data[b"run_id"].decode())
                agent_key = data[b"agent_key"].decode()

                # Filter by agent_keys if specified
                if agent_keys and agent_key not in agent_keys:
                    # Acknowledge but don't process
                    await redis.xack(self.stream_key, self.group_name, msg_id)
                    continue

                # Update database with lease
                run = await self._claim_in_db(run_id, worker_id, lease_expires)
                if run:
                    claimed.append(run)
                    # Acknowledge the message
                    await redis.xack(self.stream_key, self.group_name, msg_id)
                else:
                    # Run not found or already claimed, acknowledge anyway
                    await redis.xack(self.stream_key, self.group_name, msg_id)

        return claimed

    @sync_to_async
    def _claim_in_db(
        self, run_id: UUID, worker_id: str, lease_expires: datetime
    ) -> Optional[QueuedRun]:
        """Claim run in database."""
        now = datetime.now(timezone.utc)

        with transaction.atomic():
            try:
                run = AgentRun.objects.select_for_update(nowait=True).get(
                    id=run_id,
                    status__in=[RunStatus.QUEUED, RunStatus.RUNNING],
                )
            except (AgentRun.DoesNotExist, Exception):
                return None

            # Check if already claimed by another worker
            if run.status == RunStatus.RUNNING and run.lease_expires_at > now:
                return None

            run.status = RunStatus.RUNNING
            run.lease_owner = worker_id
            run.lease_expires_at = lease_expires
            if run.started_at is None:
                run.started_at = now
            run.save()

            return QueuedRun(
                run_id=run.id,
                agent_key=run.agent_key,
                attempt=run.attempt,
                lease_expires_at=lease_expires,
                input=run.input,
                metadata=run.metadata,
            )

    async def extend_lease(self, run_id: UUID, worker_id: str, seconds: int) -> bool:
        """Extend lease in database."""

        @sync_to_async
        def _extend():
            now = datetime.now(timezone.utc)
            new_expires = now + timedelta(seconds=seconds)

            updated = AgentRun.objects.filter(
                id=run_id,
                lease_owner=worker_id,
                status=RunStatus.RUNNING,
            ).update(lease_expires_at=new_expires)

            return updated > 0

        return await _extend()

    async def release(
        self,
        run_id: UUID,
        worker_id: str,
        success: bool,
        output: Optional[dict] = None,
        error: Optional[dict] = None,
    ) -> None:
        """Release run after completion."""

        @sync_to_async
        def _release():
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

        await _release()

    async def requeue_for_retry(
        self,
        run_id: UUID,
        worker_id: str,
        error: dict,
        delay_seconds: int = 0,
    ) -> bool:
        """Requeue for retry - re-add to stream."""

        @sync_to_async
        def _check_and_update():
            with transaction.atomic():
                try:
                    run = AgentRun.objects.select_for_update().get(
                        id=run_id, lease_owner=worker_id
                    )
                except AgentRun.DoesNotExist:
                    return None

                if run.attempt >= run.max_attempts:
                    run.status = RunStatus.FAILED
                    run.error = error
                    run.finished_at = datetime.now(timezone.utc)
                    run.lease_owner = ""
                    run.lease_expires_at = None
                    run.save()
                    return None

                run.status = RunStatus.QUEUED
                run.attempt += 1
                run.error = error
                run.lease_owner = ""
                run.lease_expires_at = None
                run.save()
                return run.agent_key

        agent_key = await _check_and_update()
        if agent_key:
            # Re-add to stream
            await self.enqueue(run_id, agent_key)
            return True
        return False

    async def cancel(self, run_id: UUID) -> bool:
        """Mark run for cancellation."""

        @sync_to_async
        def _cancel():
            now = datetime.now(timezone.utc)
            updated = AgentRun.objects.filter(
                id=run_id,
                status__in=[RunStatus.QUEUED, RunStatus.RUNNING],
            ).update(cancel_requested_at=now)
            return updated > 0

        return await _cancel()

    async def is_cancelled(self, run_id: UUID) -> bool:
        """Check if cancellation was requested."""

        @sync_to_async
        def _is_cancelled():
            try:
                run = AgentRun.objects.get(id=run_id)
                return run.cancel_requested_at is not None
            except AgentRun.DoesNotExist:
                return False

        return await _is_cancelled()

    async def recover_expired_leases(self) -> int:
        """Recover runs with expired leases and re-add to stream."""
        redis = await self._get_redis()

        @sync_to_async
        def _get_expired():
            now = datetime.now(timezone.utc)
            return list(
                AgentRun.objects.filter(
                    status=RunStatus.RUNNING,
                    lease_expires_at__lt=now,
                ).values("id", "agent_key", "attempt", "max_attempts")
            )

        expired = await _get_expired()

        @sync_to_async
        def _update_run(run_data):
            now = datetime.now(timezone.utc)
            run = AgentRun.objects.get(id=run_data["id"])

            if run_data["attempt"] >= run_data["max_attempts"]:
                run.status = RunStatus.TIMED_OUT
                run.finished_at = now
                run.error = {
                    "type": "LeaseExpired",
                    "message": "Worker lease expired without completion",
                    "retriable": False,
                }
                requeue = False
            else:
                run.status = RunStatus.QUEUED
                run.attempt += 1
                requeue = True

            run.lease_owner = ""
            run.lease_expires_at = None
            run.save()
            return requeue

        count = 0
        for run_data in expired:
            requeue = await _update_run(run_data)
            if requeue:
                await self.enqueue(run_data["id"], run_data["agent_key"])
            count += 1

        return count

    async def close(self) -> None:
        """Close Redis connection."""
        if self._redis:
            await self._redis.close()
            self._redis = None
