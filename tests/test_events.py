"""
Tests for django_agent_runtime event bus implementations.

Tests both sync and async event bus implementations.
"""

import pytest
from uuid import uuid4
from unittest.mock import patch, AsyncMock, MagicMock

from django.conf import settings
from django.contrib.auth import get_user_model

from django_agent_runtime.models import AgentRun, AgentEvent, AgentConversation
from django_agent_runtime.runtime.events.sync import SyncDatabaseEventBus
from django_agent_runtime.runtime.events.base import Event

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


@pytest.mark.django_db(transaction=True)
class TestSyncDatabaseEventBus:
    """Tests for SyncDatabaseEventBus."""

    @pytest.fixture
    def event_bus(self):
        """Create a SyncDatabaseEventBus instance."""
        return SyncDatabaseEventBus()

    def test_publish_event(self, event_bus, agent_run):
        """Test publishing an event."""
        event = Event(
            run_id=agent_run.id,
            seq=0,
            event_type="test.event",
            payload={"data": "test"},
        )

        event_bus.publish(event)

        # Verify event was saved to database
        db_event = AgentEvent.objects.get(run=agent_run, seq=0)
        assert db_event.event_type == "test.event"
        assert db_event.payload["data"] == "test"

    def test_publish_multiple_events(self, event_bus, agent_run):
        """Test publishing multiple events."""
        for i in range(5):
            event = Event(
                run_id=agent_run.id,
                seq=i,
                event_type=f"event_{i}",
                payload={"index": i},
            )
            event_bus.publish(event)

        events = AgentEvent.objects.filter(run=agent_run).order_by("seq")
        assert events.count() == 5

    def test_get_events(self, event_bus, agent_run):
        """Test getting events for a run."""
        # Create some events
        for i in range(3):
            AgentEvent.objects.create(
                run=agent_run,
                seq=i,
                event_type=f"event_{i}",
                payload={},
            )

        events = event_bus.get_events(agent_run.id)

        assert len(events) == 3
        assert all(isinstance(e, Event) for e in events)

    def test_get_events_from_seq(self, event_bus, agent_run):
        """Test getting events from a specific sequence."""
        for i in range(5):
            AgentEvent.objects.create(
                run=agent_run,
                seq=i,
                event_type=f"event_{i}",
                payload={},
            )

        events = event_bus.get_events(agent_run.id, from_seq=2)

        assert len(events) == 3
        assert events[0].seq == 2

    def test_get_events_with_range(self, event_bus, agent_run):
        """Test getting events within a range."""
        for i in range(5):
            AgentEvent.objects.create(
                run=agent_run,
                seq=i,
                event_type=f"event_{i}",
                payload={},
            )

        events = event_bus.get_events(agent_run.id, from_seq=1, to_seq=3)

        assert len(events) == 3
        assert events[0].seq == 1
        assert events[-1].seq == 3

    def test_get_next_seq(self, event_bus, agent_run):
        """Test getting next sequence number."""
        # No events yet
        assert event_bus.get_next_seq(agent_run.id) == 0

        # Add some events
        for i in range(3):
            AgentEvent.objects.create(
                run=agent_run,
                seq=i,
                event_type=f"event_{i}",
                payload={},
            )

        assert event_bus.get_next_seq(agent_run.id) == 3


class TestEvent:
    """Tests for Event dataclass."""
    
    def test_event_creation(self):
        """Test creating an Event."""
        run_id = uuid4()
        event = Event(
            run_id=run_id,
            seq=0,
            event_type="test.event",
            payload={"key": "value"},
        )
        
        assert event.run_id == run_id
        assert event.seq == 0
        assert event.event_type == "test.event"
        assert event.payload["key"] == "value"
    
    def test_event_to_dict(self):
        """Test converting Event to dict."""
        run_id = uuid4()
        event = Event(
            run_id=run_id,
            seq=0,
            event_type="test.event",
            payload={"key": "value"},
        )
        
        data = event.to_dict()
        
        assert data["run_id"] == str(run_id)
        assert data["seq"] == 0
        assert data["type"] == "test.event"
        assert data["payload"]["key"] == "value"
    
    def test_event_from_dict(self):
        """Test creating Event from dict."""
        from datetime import datetime, timezone

        run_id = uuid4()
        ts = datetime.now(timezone.utc)
        data = {
            "run_id": str(run_id),
            "seq": 5,
            "type": "test.event",
            "payload": {"data": "test"},
            "ts": ts.isoformat(),
        }

        event = Event.from_dict(data)

        assert event.run_id == run_id
        assert event.seq == 5
        assert event.event_type == "test.event"

