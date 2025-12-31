"""
Tests for django_agent_runtime models.
"""

import pytest
from uuid import uuid4
from django.utils import timezone

from django_agent_runtime.models import (
    AgentRun,
    AgentConversation,
    AgentEvent,
    AgentCheckpoint,
)
from django_agent_runtime.models.base import RunStatus


@pytest.mark.django_db
class TestAgentConversation:
    """Tests for AgentConversation model."""
    
    def test_create_conversation(self, user):
        """Test creating a conversation."""
        conv = AgentConversation.objects.create(
            user=user,
            agent_key="test-agent",
            title="Test Conversation",
        )
        
        assert conv.id is not None
        assert conv.agent_key == "test-agent"
        assert conv.title == "Test Conversation"
        assert conv.user == user
    
    def test_conversation_metadata(self, user):
        """Test conversation metadata field."""
        conv = AgentConversation.objects.create(
            user=user,
            agent_key="test-agent",
            metadata={"custom_field": "value"},
        )
        
        assert conv.metadata["custom_field"] == "value"
    
    def test_conversation_str(self, conversation):
        """Test conversation string representation."""
        assert str(conversation.id) in str(conversation)


@pytest.mark.django_db
class TestAgentRun:
    """Tests for AgentRun model."""
    
    def test_create_run(self, conversation):
        """Test creating a run."""
        run = AgentRun.objects.create(
            conversation=conversation,
            agent_key="test-agent",
            input={"messages": [{"role": "user", "content": "Hello"}]},
        )

        assert run.id is not None
        assert run.status == RunStatus.QUEUED
        assert run.attempt == 1  # Starts at 1 (first attempt)
        assert run.max_attempts == 3
    
    def test_run_status_transitions(self, agent_run):
        """Test run status transitions."""
        assert agent_run.status == RunStatus.QUEUED
        
        agent_run.status = RunStatus.RUNNING
        agent_run.started_at = timezone.now()
        agent_run.save()
        
        agent_run.refresh_from_db()
        assert agent_run.status == RunStatus.RUNNING
        assert agent_run.started_at is not None
    
    def test_is_terminal_property(self, agent_run):
        """Test is_terminal property."""
        assert not agent_run.is_terminal
        
        agent_run.status = RunStatus.SUCCEEDED
        assert agent_run.is_terminal
        
        agent_run.status = RunStatus.FAILED
        assert agent_run.is_terminal
        
        agent_run.status = RunStatus.CANCELLED
        assert agent_run.is_terminal
    
    def test_idempotency_key(self, conversation):
        """Test idempotency key uniqueness."""
        run1 = AgentRun.objects.create(
            conversation=conversation,
            agent_key="test-agent",
            input={"messages": []},
            idempotency_key="unique-key-123",
        )
        
        # Should raise IntegrityError for duplicate key
        with pytest.raises(Exception):
            AgentRun.objects.create(
                conversation=conversation,
                agent_key="test-agent",
                input={"messages": []},
                idempotency_key="unique-key-123",
            )
    
    def test_run_without_conversation(self, db):
        """Test creating a run without a conversation."""
        run = AgentRun.objects.create(
            agent_key="standalone-agent",
            input={"messages": [{"role": "user", "content": "Hello"}]},
        )
        
        assert run.conversation is None
        assert run.agent_key == "standalone-agent"


@pytest.mark.django_db
class TestAgentEvent:
    """Tests for AgentEvent model."""
    
    def test_create_event(self, agent_run):
        """Test creating an event."""
        event = AgentEvent.objects.create(
            run=agent_run,
            seq=0,
            event_type="run.started",
            payload={"timestamp": timezone.now().isoformat()},
        )
        
        assert event.id is not None
        assert event.seq == 0
        assert event.event_type == "run.started"
    
    def test_event_ordering(self, agent_run):
        """Test events are ordered by sequence."""
        for i in range(5):
            AgentEvent.objects.create(
                run=agent_run,
                seq=i,
                event_type=f"event_{i}",
                payload={},
            )
        
        events = list(AgentEvent.objects.filter(run=agent_run).order_by("seq"))
        assert len(events) == 5
        assert [e.seq for e in events] == [0, 1, 2, 3, 4]
    
    def test_event_unique_together(self, agent_run):
        """Test event seq is unique per run."""
        AgentEvent.objects.create(
            run=agent_run,
            seq=0,
            event_type="first",
            payload={},
        )
        
        with pytest.raises(Exception):
            AgentEvent.objects.create(
                run=agent_run,
                seq=0,
                event_type="duplicate",
                payload={},
            )


@pytest.mark.django_db
class TestAgentCheckpoint:
    """Tests for AgentCheckpoint model."""
    
    def test_create_checkpoint(self, agent_run):
        """Test creating a checkpoint."""
        checkpoint = AgentCheckpoint.objects.create(
            run=agent_run,
            seq=0,
            state={"iteration": 0, "messages": []},
        )
        
        assert checkpoint.id is not None
        assert checkpoint.seq == 0
        assert checkpoint.state["iteration"] == 0
    
    def test_checkpoint_unique_together(self, agent_run):
        """Test checkpoint seq is unique per run."""
        AgentCheckpoint.objects.create(
            run=agent_run,
            seq=0,
            state={},
        )
        
        with pytest.raises(Exception):
            AgentCheckpoint.objects.create(
                run=agent_run,
                seq=0,
                state={},
            )

