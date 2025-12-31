"""
Tests for django_agent_runtime event bus implementations.
"""

import pytest
from uuid import uuid4
from unittest.mock import patch, AsyncMock, MagicMock

from django_agent_runtime.models import AgentRun, AgentEvent
from django_agent_runtime.runtime.events.db import DatabaseEventBus
from django_agent_runtime.runtime.events.base import Event


@pytest.mark.django_db
class TestDatabaseEventBus:
    """Tests for DatabaseEventBus."""
    
    @pytest.fixture
    def event_bus(self):
        """Create a DatabaseEventBus instance."""
        return DatabaseEventBus()
    
    @pytest.mark.asyncio
    async def test_publish_event(self, event_bus, agent_run):
        """Test publishing an event."""
        event = Event(
            run_id=agent_run.id,
            seq=0,
            event_type="test.event",
            payload={"data": "test"},
        )
        
        await event_bus.publish(event)
        
        # Verify event was saved to database
        db_event = AgentEvent.objects.get(run=agent_run, seq=0)
        assert db_event.event_type == "test.event"
        assert db_event.payload["data"] == "test"
    
    @pytest.mark.asyncio
    async def test_publish_multiple_events(self, event_bus, agent_run):
        """Test publishing multiple events."""
        for i in range(5):
            event = Event(
                run_id=agent_run.id,
                seq=i,
                event_type=f"event_{i}",
                payload={"index": i},
            )
            await event_bus.publish(event)
        
        events = AgentEvent.objects.filter(run=agent_run).order_by("seq")
        assert events.count() == 5
    
    @pytest.mark.asyncio
    async def test_get_events(self, event_bus, agent_run):
        """Test getting events for a run."""
        # Create some events
        for i in range(3):
            AgentEvent.objects.create(
                run=agent_run,
                seq=i,
                event_type=f"event_{i}",
                payload={},
            )
        
        events = await event_bus.get_events(agent_run.id)
        
        assert len(events) == 3
        assert all(isinstance(e, Event) for e in events)
    
    @pytest.mark.asyncio
    async def test_get_events_from_seq(self, event_bus, agent_run):
        """Test getting events from a specific sequence."""
        for i in range(5):
            AgentEvent.objects.create(
                run=agent_run,
                seq=i,
                event_type=f"event_{i}",
                payload={},
            )
        
        events = await event_bus.get_events(agent_run.id, from_seq=2)
        
        assert len(events) == 3
        assert events[0].seq == 2
    
    @pytest.mark.asyncio
    async def test_subscribe_gets_existing_events(self, event_bus, agent_run):
        """Test that subscribe yields existing events."""
        # Create some events first
        for i in range(3):
            AgentEvent.objects.create(
                run=agent_run,
                seq=i,
                event_type=f"event_{i}",
                payload={},
            )
        
        # Add terminal event
        AgentEvent.objects.create(
            run=agent_run,
            seq=3,
            event_type="run.succeeded",
            payload={},
        )
        
        events = []
        async for event in event_bus.subscribe(agent_run.id):
            events.append(event)
            if event.event_type == "run.succeeded":
                break
        
        assert len(events) == 4


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
        run_id = uuid4()
        data = {
            "run_id": str(run_id),
            "seq": 5,
            "type": "test.event",
            "payload": {"data": "test"},
        }
        
        event = Event.from_dict(data)
        
        assert event.run_id == run_id
        assert event.seq == 5
        assert event.event_type == "test.event"

