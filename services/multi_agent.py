"""
Multi-agent system services.

Provides high-level operations for managing multi-agent systems:
- Publishing system versions (snapshot all agents)
- Deploying system versions (make active)
- Exporting systems for standalone execution
"""

import logging
from typing import Optional

from django.utils import timezone

from django.db import transaction

from django_agent_runtime.models import (
    AgentDefinition,
    AgentRevision,
    AgentSystem,
    AgentSystemMember,
    AgentSystemVersion,
    AgentSystemSnapshot,
)

logger = logging.getLogger(__name__)


def create_system(
    slug: str,
    name: str,
    entry_agent: AgentDefinition,
    description: str = "",
    owner=None,
) -> AgentSystem:
    """
    Create a new multi-agent system.
    
    Args:
        slug: Unique identifier for the system
        name: Human-readable name
        entry_agent: The agent that handles initial requests
        description: Optional description
        owner: Optional owner user
        
    Returns:
        The created AgentSystem
    """
    system = AgentSystem.objects.create(
        slug=slug,
        name=name,
        entry_agent=entry_agent,
        description=description,
        owner=owner,
    )
    
    # Automatically add entry agent as a member
    AgentSystemMember.objects.create(
        system=system,
        agent=entry_agent,
        role=AgentSystemMember.Role.ENTRY_POINT,
        order=0,
    )
    
    logger.info(f"Created agent system: {slug}")
    return system


def add_agent_to_system(
    system: AgentSystem,
    agent: AgentDefinition,
    role: str = AgentSystemMember.Role.SPECIALIST,
    notes: str = "",
) -> AgentSystemMember:
    """
    Add an agent to a system.
    
    Args:
        system: The system to add to
        agent: The agent to add
        role: Role in the system (specialist, utility, etc.)
        notes: Optional notes about the agent's role
        
    Returns:
        The created AgentSystemMember
    """
    # Get next order number
    max_order = system.members.aggregate(
        max_order=models.Max('order')
    )['max_order'] or 0
    
    member = AgentSystemMember.objects.create(
        system=system,
        agent=agent,
        role=role,
        notes=notes,
        order=max_order + 1,
    )
    
    logger.info(f"Added {agent.slug} to system {system.slug} as {role}")
    return member


@transaction.atomic
def publish_system_version(
    system: AgentSystem,
    version: str,
    notes: str = "",
    user=None,
    make_active: bool = False,
) -> AgentSystemVersion:
    """
    Publish a new version of a multi-agent system.
    
    This snapshots the current state of all member agents,
    creating revision records if needed.
    
    Args:
        system: The system to publish
        version: Version string (e.g., "1.0.0")
        notes: Release notes
        user: User performing the publish
        make_active: Whether to make this the active version
        
    Returns:
        The created AgentSystemVersion
    """
    # Create the version record
    system_version = AgentSystemVersion.objects.create(
        system=system,
        version=version,
        notes=notes,
        created_by=user,
        is_draft=False,
        is_active=make_active,
        published_at=timezone.now() if not make_active else None,
    )
    
    if make_active:
        system_version.published_at = timezone.now()
        system_version.save()
    
    # Snapshot each member agent
    for member in system.members.select_related('agent').all():
        agent = member.agent
        
        # Create a revision of the current agent state
        revision = AgentRevision.create_from_agent(
            agent,
            comment=f"Snapshot for system {system.slug} v{version}",
            user=user,
        )
        
        # Create the snapshot linking version -> agent -> revision
        AgentSystemSnapshot.objects.create(
            system_version=system_version,
            agent=agent,
            pinned_revision=revision,
        )
        
        logger.info(f"Snapshotted {agent.slug} r{revision.revision_number} for {system.slug} v{version}")
    
    logger.info(f"Published system version: {system.slug} v{version}")
    return system_version


@transaction.atomic
def deploy_system_version(
    system_version: AgentSystemVersion,
) -> None:
    """
    Deploy a system version (make it active).
    
    This deactivates any currently active version and
    activates the specified version.
    
    Args:
        system_version: The version to deploy
    """
    system_version.is_active = True
    system_version.is_draft = False
    system_version.published_at = system_version.published_at or timezone.now()
    system_version.save()
    
    logger.info(f"Deployed system version: {system_version.system.slug} v{system_version.version}")


def export_system_version(
    system_version: AgentSystemVersion,
    embed_agents: bool = True,
) -> dict:
    """
    Export a system version as a portable configuration.
    
    Args:
        system_version: The version to export
        embed_agents: If True, embed full agent configs inline.
                     If False, only include agent slugs.
                     
    Returns:
        Dictionary that can be saved as JSON and loaded by agent_runtime_core
    """
    return system_version.export_config(embed_agents=embed_agents)


def export_system_version_to_file(
    system_version: AgentSystemVersion,
    path: str,
    embed_agents: bool = True,
) -> None:
    """
    Export a system version to a JSON file.
    
    Args:
        system_version: The version to export
        path: File path to write to
        embed_agents: If True, embed full agent configs inline.
    """
    import json
    from pathlib import Path
    
    config = export_system_version(system_version, embed_agents=embed_agents)
    Path(path).write_text(json.dumps(config, indent=2))
    
    logger.info(f"Exported {system_version.system.slug} v{system_version.version} to {path}")


def get_active_system_version(system: AgentSystem) -> Optional[AgentSystemVersion]:
    """
    Get the currently active version of a system.
    
    Args:
        system: The system to query
        
    Returns:
        The active AgentSystemVersion or None
    """
    return system.versions.filter(is_active=True).first()


def discover_system_agents(entry_agent: AgentDefinition) -> list[AgentDefinition]:
    """
    Discover all agents reachable from an entry agent.
    
    Traverses the sub-agent tool references to find all agents
    that could be invoked in a multi-agent system.
    
    Args:
        entry_agent: The entry point agent
        
    Returns:
        List of all reachable agents (including entry_agent)
    """
    from django_agent_runtime.models import AgentTool
    
    discovered = {entry_agent.slug: entry_agent}
    to_visit = [entry_agent]
    
    while to_visit:
        current = to_visit.pop()
        
        # Find all sub-agent tools
        for tool in current.tools.filter(
            tool_type=AgentTool.ToolType.SUBAGENT,
            is_active=True,
        ).select_related('subagent'):
            if tool.subagent and tool.subagent.slug not in discovered:
                discovered[tool.subagent.slug] = tool.subagent
                to_visit.append(tool.subagent)
    
    return list(discovered.values())


def create_system_from_entry_agent(
    slug: str,
    name: str,
    entry_agent: AgentDefinition,
    description: str = "",
    owner=None,
    auto_discover: bool = True,
) -> AgentSystem:
    """
    Create a system from an entry agent, optionally auto-discovering sub-agents.
    
    Args:
        slug: Unique identifier for the system
        name: Human-readable name
        entry_agent: The agent that handles initial requests
        description: Optional description
        owner: Optional owner user
        auto_discover: If True, automatically add all reachable sub-agents
        
    Returns:
        The created AgentSystem with all members
    """
    system = create_system(
        slug=slug,
        name=name,
        entry_agent=entry_agent,
        description=description,
        owner=owner,
    )
    
    if auto_discover:
        # Discover and add all reachable agents
        all_agents = discover_system_agents(entry_agent)
        
        for agent in all_agents:
            if agent.slug != entry_agent.slug:  # Entry agent already added
                add_agent_to_system(
                    system=system,
                    agent=agent,
                    role=AgentSystemMember.Role.SPECIALIST,
                )
    
    return system


# Need to import models for the aggregate
from django.db import models

