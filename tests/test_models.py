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


# =============================================================================
# Multi-Agent System Model Tests
# =============================================================================

from django_agent_runtime.models import (
    AgentDefinition,
    AgentVersion,
    AgentTool,
    AgentRevision,
    AgentSystem,
    AgentSystemMember,
    AgentSystemVersion,
    AgentSystemSnapshot,
)


@pytest.fixture
def agent_definition(db, user):
    """Create a test agent definition."""
    agent = AgentDefinition.objects.create(
        slug="test-agent",
        name="Test Agent",
        description="A test agent",
        owner=user,
    )
    # Create a version
    AgentVersion.objects.create(
        agent=agent,
        version="1.0",
        system_prompt="You are a test agent.",
        model="gpt-4o",
        is_active=True,
    )
    return agent


@pytest.fixture
def sub_agent(db, user):
    """Create a sub-agent definition."""
    agent = AgentDefinition.objects.create(
        slug="sub-agent",
        name="Sub Agent",
        description="A sub-agent for testing",
        owner=user,
    )
    AgentVersion.objects.create(
        agent=agent,
        version="1.0",
        system_prompt="You are a sub-agent.",
        model="gpt-4o",
        is_active=True,
    )
    return agent


@pytest.fixture
def agent_with_subagent_tool(db, user, agent_definition, sub_agent):
    """Create an agent with a sub-agent tool."""
    AgentTool.objects.create(
        agent=agent_definition,
        name="call_sub_agent",
        tool_type=AgentTool.ToolType.SUBAGENT,
        description="Call the sub-agent",
        subagent=sub_agent,
    )
    return agent_definition


@pytest.mark.django_db
class TestAgentSystem:
    """Tests for AgentSystem model."""

    def test_create_system(self, user, agent_definition):
        """Test creating an agent system."""
        system = AgentSystem.objects.create(
            slug="test-system",
            name="Test System",
            description="A test multi-agent system",
            entry_agent=agent_definition,
            owner=user,
        )

        assert system.id is not None
        assert system.slug == "test-system"
        assert system.entry_agent == agent_definition
        assert system.is_active is True

    def test_system_str(self, user, agent_definition):
        """Test system string representation."""
        system = AgentSystem.objects.create(
            slug="test-system",
            name="Test System",
            entry_agent=agent_definition,
            owner=user,
        )
        assert "Test System" in str(system)
        assert "test-system" in str(system)

    def test_get_all_agents(self, user, agent_definition, sub_agent):
        """Test getting all agents in a system."""
        system = AgentSystem.objects.create(
            slug="test-system",
            name="Test System",
            entry_agent=agent_definition,
            owner=user,
        )
        AgentSystemMember.objects.create(
            system=system,
            agent=agent_definition,
            role=AgentSystemMember.Role.ENTRY_POINT,
        )
        AgentSystemMember.objects.create(
            system=system,
            agent=sub_agent,
            role=AgentSystemMember.Role.SPECIALIST,
        )

        agents = system.get_all_agents()
        assert len(agents) == 2
        assert agent_definition in agents
        assert sub_agent in agents

    def test_get_dependency_graph(self, user, agent_with_subagent_tool, sub_agent):
        """Test building dependency graph."""
        system = AgentSystem.objects.create(
            slug="test-system",
            name="Test System",
            entry_agent=agent_with_subagent_tool,
            owner=user,
        )
        AgentSystemMember.objects.create(
            system=system,
            agent=agent_with_subagent_tool,
            role=AgentSystemMember.Role.ENTRY_POINT,
        )
        AgentSystemMember.objects.create(
            system=system,
            agent=sub_agent,
            role=AgentSystemMember.Role.SPECIALIST,
        )

        graph = system.get_dependency_graph()
        assert agent_with_subagent_tool.slug in graph
        assert sub_agent.slug in graph[agent_with_subagent_tool.slug]


@pytest.mark.django_db
class TestAgentSystemMember:
    """Tests for AgentSystemMember model."""

    def test_create_member(self, user, agent_definition):
        """Test creating a system member."""
        system = AgentSystem.objects.create(
            slug="test-system",
            name="Test System",
            entry_agent=agent_definition,
            owner=user,
        )
        member = AgentSystemMember.objects.create(
            system=system,
            agent=agent_definition,
            role=AgentSystemMember.Role.ENTRY_POINT,
            notes="Entry point agent",
        )

        assert member.id is not None
        assert member.role == AgentSystemMember.Role.ENTRY_POINT
        assert member.notes == "Entry point agent"

    def test_unique_agent_per_system(self, user, agent_definition):
        """Test that an agent can only be added once per system."""
        system = AgentSystem.objects.create(
            slug="test-system",
            name="Test System",
            entry_agent=agent_definition,
            owner=user,
        )
        AgentSystemMember.objects.create(
            system=system,
            agent=agent_definition,
            role=AgentSystemMember.Role.ENTRY_POINT,
        )

        from django.db import IntegrityError
        with pytest.raises(IntegrityError):
            AgentSystemMember.objects.create(
                system=system,
                agent=agent_definition,
                role=AgentSystemMember.Role.SPECIALIST,
            )


@pytest.mark.django_db
class TestAgentSystemVersion:
    """Tests for AgentSystemVersion model."""

    def test_create_version(self, user, agent_definition):
        """Test creating a system version."""
        system = AgentSystem.objects.create(
            slug="test-system",
            name="Test System",
            entry_agent=agent_definition,
            owner=user,
        )
        version = AgentSystemVersion.objects.create(
            system=system,
            version="1.0.0",
            notes="Initial release",
            created_by=user,
        )

        assert version.id is not None
        assert version.version == "1.0.0"
        assert version.is_draft is True
        assert version.is_active is False

    def test_only_one_active_version(self, user, agent_definition):
        """Test that only one version can be active at a time."""
        system = AgentSystem.objects.create(
            slug="test-system",
            name="Test System",
            entry_agent=agent_definition,
            owner=user,
        )
        v1 = AgentSystemVersion.objects.create(
            system=system,
            version="1.0.0",
            is_active=True,
        )
        v2 = AgentSystemVersion.objects.create(
            system=system,
            version="2.0.0",
            is_active=True,
        )

        # Refresh v1 from database
        v1.refresh_from_db()
        assert v1.is_active is False
        assert v2.is_active is True

    def test_version_str(self, user, agent_definition):
        """Test version string representation."""
        system = AgentSystem.objects.create(
            slug="test-system",
            name="Test System",
            entry_agent=agent_definition,
            owner=user,
        )
        version = AgentSystemVersion.objects.create(
            system=system,
            version="1.0.0",
            is_active=True,
            is_draft=False,
        )
        assert "1.0.0" in str(version)
        assert "active" in str(version)


@pytest.mark.django_db
class TestAgentSystemSnapshot:
    """Tests for AgentSystemSnapshot model."""

    def test_create_snapshot(self, user, agent_definition):
        """Test creating a system snapshot."""
        system = AgentSystem.objects.create(
            slug="test-system",
            name="Test System",
            entry_agent=agent_definition,
            owner=user,
        )
        version = AgentSystemVersion.objects.create(
            system=system,
            version="1.0.0",
        )
        revision = AgentRevision.create_from_agent(agent_definition)

        snapshot = AgentSystemSnapshot.objects.create(
            system_version=version,
            agent=agent_definition,
            pinned_revision=revision,
        )

        assert snapshot.id is not None
        assert snapshot.pinned_revision == revision

    def test_get_agent_config(self, user, agent_definition):
        """Test getting agent config from snapshot."""
        system = AgentSystem.objects.create(
            slug="test-system",
            name="Test System",
            entry_agent=agent_definition,
            owner=user,
        )
        version = AgentSystemVersion.objects.create(
            system=system,
            version="1.0.0",
        )
        revision = AgentRevision.create_from_agent(agent_definition)

        snapshot = AgentSystemSnapshot.objects.create(
            system_version=version,
            agent=agent_definition,
            pinned_revision=revision,
        )

        config = snapshot.get_agent_config()
        assert config["slug"] == "test-agent"
        assert config["name"] == "Test Agent"


# =============================================================================
# Multi-Agent Service Tests
# =============================================================================

from django_agent_runtime.services.multi_agent import (
    create_system,
    add_agent_to_system,
    publish_system_version,
    deploy_system_version,
    export_system_version,
    discover_system_agents,
    create_system_from_entry_agent,
    get_active_system_version,
)


@pytest.mark.django_db
class TestMultiAgentServices:
    """Tests for multi-agent system services."""

    def test_create_system(self, user, agent_definition):
        """Test creating a system via service."""
        system = create_system(
            slug="service-test-system",
            name="Service Test System",
            entry_agent=agent_definition,
            description="Created via service",
            owner=user,
        )

        assert system.slug == "service-test-system"
        assert system.entry_agent == agent_definition
        # Entry agent should be auto-added as member
        assert system.members.count() == 1
        assert system.members.first().role == AgentSystemMember.Role.ENTRY_POINT

    def test_add_agent_to_system(self, user, agent_definition, sub_agent):
        """Test adding an agent to a system."""
        system = create_system(
            slug="add-test-system",
            name="Add Test System",
            entry_agent=agent_definition,
            owner=user,
        )

        member = add_agent_to_system(
            system=system,
            agent=sub_agent,
            role=AgentSystemMember.Role.SPECIALIST,
            notes="Added via service",
        )

        assert member.agent == sub_agent
        assert member.role == AgentSystemMember.Role.SPECIALIST
        assert system.members.count() == 2

    def test_publish_system_version(self, user, agent_definition, sub_agent):
        """Test publishing a system version."""
        system = create_system(
            slug="publish-test-system",
            name="Publish Test System",
            entry_agent=agent_definition,
            owner=user,
        )
        add_agent_to_system(system, sub_agent)

        version = publish_system_version(
            system=system,
            version="1.0.0",
            notes="First release",
            user=user,
        )

        assert version.version == "1.0.0"
        assert version.is_draft is False
        # Should have snapshots for both agents
        assert version.snapshots.count() == 2

    def test_publish_and_deploy(self, user, agent_definition):
        """Test publishing and deploying a version."""
        system = create_system(
            slug="deploy-test-system",
            name="Deploy Test System",
            entry_agent=agent_definition,
            owner=user,
        )

        version = publish_system_version(
            system=system,
            version="1.0.0",
            user=user,
            make_active=False,
        )
        assert version.is_active is False

        deploy_system_version(version)
        version.refresh_from_db()
        assert version.is_active is True

    def test_get_active_system_version(self, user, agent_definition):
        """Test getting the active version."""
        system = create_system(
            slug="active-test-system",
            name="Active Test System",
            entry_agent=agent_definition,
            owner=user,
        )

        # No active version yet
        assert get_active_system_version(system) is None

        version = publish_system_version(
            system=system,
            version="1.0.0",
            user=user,
            make_active=True,
        )

        active = get_active_system_version(system)
        assert active == version

    def test_discover_system_agents(self, user, agent_with_subagent_tool, sub_agent):
        """Test discovering agents from entry point."""
        agents = discover_system_agents(agent_with_subagent_tool)

        assert len(agents) == 2
        slugs = [a.slug for a in agents]
        assert agent_with_subagent_tool.slug in slugs
        assert sub_agent.slug in slugs

    def test_create_system_from_entry_agent_with_auto_discover(
        self, user, agent_with_subagent_tool, sub_agent
    ):
        """Test creating a system with auto-discovery."""
        system = create_system_from_entry_agent(
            slug="auto-discover-system",
            name="Auto Discover System",
            entry_agent=agent_with_subagent_tool,
            owner=user,
            auto_discover=True,
        )

        # Should have both agents as members
        assert system.members.count() == 2
        member_agents = [m.agent for m in system.members.all()]
        assert agent_with_subagent_tool in member_agents
        assert sub_agent in member_agents

    def test_export_system_version(self, user, agent_definition):
        """Test exporting a system version."""
        system = create_system(
            slug="export-test-system",
            name="Export Test System",
            entry_agent=agent_definition,
            owner=user,
        )

        version = publish_system_version(
            system=system,
            version="1.0.0",
            user=user,
        )

        config = export_system_version(version, embed_agents=True)

        assert config["system_slug"] == "export-test-system"
        assert config["system_version"] == "1.0.0"
        assert "entry_agent" in config
        assert config["entry_agent"]["slug"] == "test-agent"
