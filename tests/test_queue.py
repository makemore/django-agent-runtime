"""
Tests for django_agent_runtime queue implementations.
"""

import pytest
from uuid import uuid4
from datetime import timedelta
from unittest.mock import patch, AsyncMock, MagicMock

from django.utils import timezone

from django_agent_runtime.models import AgentRun
from django_agent_runtime.models.base import RunStatus
from django_agent_runtime.runtime.queue.postgres import PostgresQueue


@pytest.mark.django_db
class TestPostgresQueue:
    """Tests for PostgresQueue."""
    
    @pytest.fixture
    def queue(self):
        """Create a PostgresQueue instance."""
        return PostgresQueue(lease_ttl_seconds=30)
    
    @pytest.mark.asyncio
    async def test_enqueue(self, queue, conversation):
        """Test enqueueing a run."""
        run = AgentRun.objects.create(
            conversation=conversation,
            agent_key="test-agent",
            input={"messages": []},
        )
        
        await queue.enqueue(run.id, "test-agent")
        
        # Run should still be queued
        run.refresh_from_db()
        assert run.status == RunStatus.QUEUED
    
    @pytest.mark.asyncio
    async def test_claim_run(self, queue, conversation):
        """Test claiming a run."""
        run = AgentRun.objects.create(
            conversation=conversation,
            agent_key="test-agent",
            input={"messages": []},
        )
        
        worker_id = "worker-1"
        claimed = await queue.claim(worker_id)
        
        assert claimed is not None
        assert claimed.id == run.id
        
        run.refresh_from_db()
        assert run.status == RunStatus.RUNNING
        assert run.lease_owner == worker_id
        assert run.lease_expires_at is not None
    
    @pytest.mark.asyncio
    async def test_claim_no_available_runs(self, queue, db):
        """Test claiming when no runs are available."""
        worker_id = "worker-1"
        claimed = await queue.claim(worker_id)
        
        assert claimed is None
    
    @pytest.mark.asyncio
    async def test_claim_respects_agent_keys_filter(self, queue, conversation):
        """Test claiming respects agent_keys filter."""
        run1 = AgentRun.objects.create(
            conversation=conversation,
            agent_key="agent-a",
            input={"messages": []},
        )
        run2 = AgentRun.objects.create(
            conversation=conversation,
            agent_key="agent-b",
            input={"messages": []},
        )
        
        # Only claim agent-b runs
        queue_filtered = PostgresQueue(
            lease_ttl_seconds=30,
            agent_keys=["agent-b"],
        )
        
        claimed = await queue_filtered.claim("worker-1")
        
        assert claimed is not None
        assert claimed.agent_key == "agent-b"
    
    @pytest.mark.asyncio
    async def test_renew_lease(self, queue, conversation):
        """Test renewing a lease."""
        run = AgentRun.objects.create(
            conversation=conversation,
            agent_key="test-agent",
            input={"messages": []},
        )
        
        worker_id = "worker-1"
        claimed = await queue.claim(worker_id)
        original_expires = claimed.lease_expires_at
        
        # Renew the lease
        success = await queue.renew_lease(run.id, worker_id)
        
        assert success
        
        run.refresh_from_db()
        assert run.lease_expires_at > original_expires
    
    @pytest.mark.asyncio
    async def test_renew_lease_wrong_owner(self, queue, conversation):
        """Test renewing lease fails for wrong owner."""
        run = AgentRun.objects.create(
            conversation=conversation,
            agent_key="test-agent",
            input={"messages": []},
        )
        
        await queue.claim("worker-1")
        
        # Try to renew with different worker
        success = await queue.renew_lease(run.id, "worker-2")
        
        assert not success
    
    @pytest.mark.asyncio
    async def test_release(self, queue, conversation):
        """Test releasing a run."""
        run = AgentRun.objects.create(
            conversation=conversation,
            agent_key="test-agent",
            input={"messages": []},
        )
        
        worker_id = "worker-1"
        await queue.claim(worker_id)
        
        await queue.release(run.id, worker_id)
        
        run.refresh_from_db()
        assert run.lease_owner is None
        assert run.lease_expires_at is None
    
    @pytest.mark.asyncio
    async def test_complete_success(self, queue, conversation):
        """Test completing a run successfully."""
        run = AgentRun.objects.create(
            conversation=conversation,
            agent_key="test-agent",
            input={"messages": []},
        )
        
        worker_id = "worker-1"
        await queue.claim(worker_id)
        
        await queue.complete(
            run.id,
            worker_id,
            success=True,
            output={"response": "Done!"},
        )
        
        run.refresh_from_db()
        assert run.status == RunStatus.SUCCEEDED
        assert run.output == {"response": "Done!"}
        assert run.finished_at is not None
    
    @pytest.mark.asyncio
    async def test_complete_failure(self, queue, conversation):
        """Test completing a run with failure."""
        run = AgentRun.objects.create(
            conversation=conversation,
            agent_key="test-agent",
            input={"messages": []},
        )
        
        worker_id = "worker-1"
        await queue.claim(worker_id)
        
        await queue.complete(
            run.id,
            worker_id,
            success=False,
            error="Something went wrong",
        )
        
        run.refresh_from_db()
        assert run.status == RunStatus.FAILED
        assert run.error == "Something went wrong"
    
    @pytest.mark.asyncio
    async def test_reclaim_expired_lease(self, queue, conversation):
        """Test reclaiming a run with expired lease."""
        run = AgentRun.objects.create(
            conversation=conversation,
            agent_key="test-agent",
            input={"messages": []},
            status=RunStatus.RUNNING,
            lease_owner="dead-worker",
            lease_expires_at=timezone.now() - timedelta(minutes=5),
        )
        
        # New worker should be able to claim
        claimed = await queue.claim("new-worker")
        
        assert claimed is not None
        assert claimed.id == run.id
        
        run.refresh_from_db()
        assert run.lease_owner == "new-worker"

