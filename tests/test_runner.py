"""
Tests for django_agent_runtime runner.

Note: Async runner tests require PostgreSQL database for proper async support.
"""

import pytest
from uuid import uuid4
from unittest.mock import patch, AsyncMock, MagicMock
from datetime import timedelta

from django.utils import timezone

from django_agent_runtime.models import AgentRun, AgentEvent
from django_agent_runtime.models.base import RunStatus
from django_agent_runtime.runtime.runner import AgentRunner, RunContextImpl
from django_agent_runtime.runtime.registry import register_runtime, get_runtime, clear_registry
from django_agent_runtime.runtime.queue.postgres import PostgresQueue
from django_agent_runtime.runtime.queue.base import QueuedRun
from django_agent_runtime.runtime.events.db import DatabaseEventBus


@pytest.fixture(autouse=True)
def clear_registry_fixture():
    """Clear the runtime registry before each test."""
    clear_registry()
    yield
    clear_registry()


@pytest.mark.skip(reason="Async runner tests require PostgreSQL database")
@pytest.mark.django_db
class TestAgentRunner:
    """Tests for AgentRunner."""

    @pytest.fixture
    def queue(self):
        """Create a PostgresQueue instance."""
        return PostgresQueue(lease_ttl_seconds=30)

    @pytest.fixture
    def event_bus(self):
        """Create a DatabaseEventBus instance."""
        return DatabaseEventBus()

    @pytest.fixture
    def runner(self, queue, event_bus, mock_runtime):
        """Create an AgentRunner instance with mock runtime."""
        register_runtime(mock_runtime)

        return AgentRunner(
            worker_id="test-worker",
            queue=queue,
            event_bus=event_bus,
        )

    @pytest.mark.asyncio
    async def test_run_once_success(self, runner, agent_run, mock_runtime):
        """Test successful run execution."""
        from datetime import datetime, timezone as tz

        # Register the runtime with matching key
        mock_runtime._key = agent_run.agent_key
        register_runtime(mock_runtime)

        # Create a QueuedRun
        queued_run = QueuedRun(
            run_id=agent_run.id,
            agent_key=agent_run.agent_key,
            attempt=1,
            lease_expires_at=datetime.now(tz.utc),
            input=agent_run.input,
            metadata={},
        )

        await runner.run_once(queued_run)

        agent_run.refresh_from_db()
        assert agent_run.status == RunStatus.SUCCEEDED
        assert mock_runtime.run_count == 1

    @pytest.mark.asyncio
    async def test_run_once_failure(self, runner, agent_run, failing_runtime):
        """Test run execution with failure."""
        from datetime import datetime, timezone as tz

        failing_runtime._key = agent_run.agent_key
        register_runtime(failing_runtime)

        queued_run = QueuedRun(
            run_id=agent_run.id,
            agent_key=agent_run.agent_key,
            attempt=1,
            lease_expires_at=datetime.now(tz.utc),
            input=agent_run.input,
            metadata={},
        )

        await runner.run_once(queued_run)

        agent_run.refresh_from_db()
        # Should be failed or re-queued for retry
        assert agent_run.status in [RunStatus.FAILED, RunStatus.QUEUED]


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


@pytest.mark.skip(reason="Async context tests require PostgreSQL database")
@pytest.mark.django_db
class TestRunContextImpl:
    """Tests for RunContextImpl."""

    @pytest.fixture
    def event_bus(self):
        return DatabaseEventBus()

    @pytest.fixture
    def queue(self):
        return PostgresQueue(lease_ttl_seconds=30)

    @pytest.mark.asyncio
    async def test_context_emit_event(self, agent_run, event_bus, queue):
        """Test emitting events from context."""
        from django_agent_runtime.runtime.interfaces import EventType, ToolRegistry

        ctx = RunContextImpl(
            run_id=agent_run.id,
            conversation_id=None,
            input_messages=agent_run.input.get("messages", []),
            params={},
            metadata={},
            tool_registry=ToolRegistry(),
            _event_bus=event_bus,
            _queue=queue,
            _worker_id="test-worker",
        )

        await ctx.emit(EventType.RUN_STARTED, {"test": "data"})

        # Verify event was created
        events = AgentEvent.objects.filter(run=agent_run)
        assert events.count() >= 1

    @pytest.mark.asyncio
    async def test_context_cancellation(self, agent_run, event_bus, queue):
        """Test context cancellation checking."""
        from django_agent_runtime.runtime.interfaces import ToolRegistry

        ctx = RunContextImpl(
            run_id=agent_run.id,
            conversation_id=None,
            input_messages=[],
            params={},
            metadata={},
            tool_registry=ToolRegistry(),
            _event_bus=event_bus,
            _queue=queue,
            _worker_id="test-worker",
        )

        # Initially not cancelled
        assert not ctx.cancelled()

        # Request cancellation
        agent_run.cancel_requested_at = timezone.now()
        agent_run.save()

        # Force a check (normally done periodically)
        ctx._is_cancelled = True
        assert ctx.cancelled()

