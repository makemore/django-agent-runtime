"""
Tests for django_agent_runtime runner.

Tests for queue dataclasses and sync components.
Async runner tests are skipped as they require more complex setup.
"""

import pytest
from uuid import uuid4
from unittest.mock import patch, AsyncMock, MagicMock
from datetime import datetime, timedelta, timezone as tz

from django.conf import settings
from django.contrib.auth import get_user_model
from django.utils import timezone

from django_agent_runtime.models import AgentRun, AgentEvent, AgentConversation
from django_agent_runtime.models.base import RunStatus
from django_agent_runtime.runtime.registry import register_runtime, get_runtime, clear_registry
from django_agent_runtime.runtime.queue.base import QueuedRun
from django_agent_runtime.runtime.queue.sync import SyncPostgresQueue
from django_agent_runtime.runtime.events.sync import SyncDatabaseEventBus

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


@pytest.fixture
def agent_run(conversation):
    """Create a test agent run."""
    return AgentRun.objects.create(
        conversation=conversation,
        agent_key="test-agent",
        input={"messages": []},
    )


@pytest.fixture(autouse=True)
def clear_registry_fixture():
    """Clear the runtime registry before each test."""
    clear_registry()
    yield
    clear_registry()


@pytest.mark.django_db
class TestQueuedRun:
    """Tests for QueuedRun dataclass."""

    def test_queued_run_creation(self, agent_run):
        """Test creating a QueuedRun."""
        from datetime import datetime, timezone as tz

        queued = QueuedRun(
            run_id=agent_run.id,
            agent_key=agent_run.agent_key,
            attempt=1,
            lease_expires_at=datetime.now(tz.utc),
            input=agent_run.input,
            metadata={},
        )

        assert queued.run_id == agent_run.id
        assert queued.agent_key == agent_run.agent_key
        assert queued.attempt == 1


@pytest.mark.django_db(transaction=True)
class TestSyncQueueIntegration:
    """Integration tests for sync queue with event bus."""

    @pytest.fixture
    def queue(self):
        return SyncPostgresQueue(lease_ttl_seconds=30)

    @pytest.fixture
    def event_bus(self):
        return SyncDatabaseEventBus()

    def test_claim_and_release_workflow(self, queue, event_bus, agent_run):
        """Test complete claim and release workflow."""
        from django_agent_runtime.runtime.events.base import Event

        # Claim the run
        claimed = queue.claim("worker-1")
        assert len(claimed) == 1
        assert claimed[0].run_id == agent_run.id

        # Emit an event
        event = Event(
            run_id=agent_run.id,
            seq=0,
            event_type="run.started",
            payload={"worker": "worker-1"},
        )
        event_bus.publish(event)

        # Verify event was saved
        events = event_bus.get_events(agent_run.id)
        assert len(events) == 1
        assert events[0].event_type == "run.started"

        # Release the run
        queue.release(
            agent_run.id,
            "worker-1",
            success=True,
            output={"result": "done"},
        )

        agent_run.refresh_from_db()
        assert agent_run.status == RunStatus.SUCCEEDED
        assert agent_run.output == {"result": "done"}

    def test_cancel_workflow(self, queue, agent_run):
        """Test cancellation workflow."""
        # Claim the run
        claimed = queue.claim("worker-1")
        assert len(claimed) == 1

        # Request cancellation
        success = queue.cancel(agent_run.id)
        assert success

        # Check cancellation
        assert queue.is_cancelled(agent_run.id)
