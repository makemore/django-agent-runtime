"""
Tests for django_agent_runtime queue implementations.

Tests both sync and async queue implementations.
"""

import pytest
from uuid import uuid4
from datetime import timedelta
from unittest.mock import patch, AsyncMock, MagicMock

from django.conf import settings
from django.contrib.auth import get_user_model
from django.utils import timezone

from django_agent_runtime.models import AgentRun, AgentConversation
from django_agent_runtime.models.base import RunStatus
from django_agent_runtime.runtime.queue.sync import SyncPostgresQueue

User = get_user_model()


@pytest.fixture
def user(db):
    """Create a test user."""
    return User.objects.create_user(
        username="testuser",
        email="test@example.com",
        password="testpass123",
    )


@pytest.fixture
def conversation(user):
    """Create a test conversation."""
    return AgentConversation.objects.create(
        user=user,
        agent_key="test-agent",
        title="Test Conversation",
    )


@pytest.mark.django_db(transaction=True)
class TestSyncPostgresQueue:
    """Tests for SyncPostgresQueue."""

    @pytest.fixture
    def queue(self):
        """Create a SyncPostgresQueue instance."""
        return SyncPostgresQueue(lease_ttl_seconds=30)

    def test_claim_run(self, queue, conversation):
        """Test claiming a run."""
        run = AgentRun.objects.create(
            conversation=conversation,
            agent_key="test-agent",
            input={"messages": []},
        )

        worker_id = "worker-1"
        claimed = queue.claim(worker_id)

        assert len(claimed) == 1
        assert claimed[0].run_id == run.id

        run.refresh_from_db()
        assert run.status == RunStatus.RUNNING
        assert run.lease_owner == worker_id
        assert run.lease_expires_at is not None

    def test_claim_no_available_runs(self, queue, db):
        """Test claiming when no runs are available."""
        worker_id = "worker-1"
        claimed = queue.claim(worker_id)

        assert claimed == []

    def test_claim_batch(self, queue, conversation):
        """Test claiming multiple runs in a batch."""
        for i in range(5):
            AgentRun.objects.create(
                conversation=conversation,
                agent_key="test-agent",
                input={"messages": []},
            )

        claimed = queue.claim("worker-1", batch_size=3)
        assert len(claimed) == 3

    def test_claim_respects_agent_keys_filter(self, queue, conversation):
        """Test claiming respects agent_keys filter."""
        AgentRun.objects.create(
            conversation=conversation,
            agent_key="agent-a",
            input={"messages": []},
        )
        AgentRun.objects.create(
            conversation=conversation,
            agent_key="agent-b",
            input={"messages": []},
        )

        # Only claim agent-b runs
        claimed = queue.claim("worker-1", agent_keys=["agent-b"])

        assert len(claimed) == 1
        assert claimed[0].agent_key == "agent-b"

    def test_extend_lease(self, queue, conversation):
        """Test extending a lease."""
        run = AgentRun.objects.create(
            conversation=conversation,
            agent_key="test-agent",
            input={"messages": []},
        )

        worker_id = "worker-1"
        claimed = queue.claim(worker_id)
        original_expires = claimed[0].lease_expires_at

        # Extend the lease
        success = queue.extend_lease(run.id, worker_id, seconds=60)

        assert success

        run.refresh_from_db()
        assert run.lease_expires_at > original_expires

    def test_extend_lease_wrong_owner(self, queue, conversation):
        """Test extending lease fails for wrong owner."""
        run = AgentRun.objects.create(
            conversation=conversation,
            agent_key="test-agent",
            input={"messages": []},
        )

        queue.claim("worker-1")

        # Try to extend with different worker
        success = queue.extend_lease(run.id, "worker-2", seconds=60)

        assert not success

    def test_release_success(self, queue, conversation):
        """Test releasing a run successfully."""
        run = AgentRun.objects.create(
            conversation=conversation,
            agent_key="test-agent",
            input={"messages": []},
        )

        worker_id = "worker-1"
        queue.claim(worker_id)

        queue.release(
            run.id,
            worker_id,
            success=True,
            output={"response": "Done!"},
        )

        run.refresh_from_db()
        assert run.status == RunStatus.SUCCEEDED
        assert run.output == {"response": "Done!"}
        assert run.finished_at is not None
        assert run.lease_owner == ""
        assert run.lease_expires_at is None

    def test_release_failure(self, queue, conversation):
        """Test releasing a run with failure."""
        run = AgentRun.objects.create(
            conversation=conversation,
            agent_key="test-agent",
            input={"messages": []},
        )

        worker_id = "worker-1"
        queue.claim(worker_id)

        queue.release(
            run.id,
            worker_id,
            success=False,
            error={"message": "Something went wrong"},
        )

        run.refresh_from_db()
        assert run.status == RunStatus.FAILED
        assert run.error == {"message": "Something went wrong"}

    def test_cancel(self, queue, conversation):
        """Test cancelling a run."""
        run = AgentRun.objects.create(
            conversation=conversation,
            agent_key="test-agent",
            input={"messages": []},
        )

        success = queue.cancel(run.id)
        assert success

        assert queue.is_cancelled(run.id)

    def test_reclaim_expired_lease(self, queue, conversation):
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
        claimed = queue.claim("new-worker")

        assert len(claimed) == 1
        assert claimed[0].run_id == run.id

        run.refresh_from_db()
        assert run.lease_owner == "new-worker"

    def test_recover_expired_leases(self, queue, conversation):
        """Test recovering expired leases."""
        # Create a run with expired lease
        run = AgentRun.objects.create(
            conversation=conversation,
            agent_key="test-agent",
            input={"messages": []},
            status=RunStatus.RUNNING,
            lease_owner="dead-worker",
            lease_expires_at=timezone.now() - timedelta(minutes=5),
        )

        count = queue.recover_expired_leases()
        assert count == 1

        run.refresh_from_db()
        assert run.status == RunStatus.QUEUED
        assert run.lease_owner == ""
