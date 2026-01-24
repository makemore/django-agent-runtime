"""
DatabaseAgentRuntime - A runtime that loads agent configuration from Django models.

This bridges Django's AgentDefinition models to the portable AgentConfig format,
allowing agents defined in the database to be executed using the same runtime
as JSON-defined agents.

Example:
    # Load from database by slug
    runtime = await DatabaseAgentRuntime.from_slug("my-agent")
    result = await runtime.run(ctx)
    
    # Or load from a specific revision
    runtime = await DatabaseAgentRuntime.from_revision(agent, revision_number=5)
    result = await runtime.run(ctx)
"""

import logging
from typing import Optional

from asgiref.sync import sync_to_async

from agent_runtime_core import AgentConfig, JsonAgentRuntime
from agent_runtime_core.interfaces import RunContext, RunResult

logger = logging.getLogger(__name__)


class DatabaseAgentRuntime(JsonAgentRuntime):
    """
    An agent runtime that loads configuration from Django database models.
    
    This extends JsonAgentRuntime to add database loading capabilities,
    while maintaining full compatibility with the portable AgentConfig format.
    """
    
    def __init__(self, config: AgentConfig, agent_id: Optional[str] = None):
        """
        Initialize the runtime with an AgentConfig.
        
        Args:
            config: The agent configuration
            agent_id: Optional database ID of the agent (for tracking)
        """
        super().__init__(config)
        self.agent_id = agent_id
    
    @classmethod
    async def from_slug(cls, slug: str) -> "DatabaseAgentRuntime":
        """
        Load a runtime from the database by agent slug.
        
        Args:
            slug: The agent's unique slug identifier
            
        Returns:
            DatabaseAgentRuntime instance
            
        Raises:
            AgentDefinition.DoesNotExist: If agent not found
        """
        from django_agent_runtime.models import AgentDefinition
        
        agent = await sync_to_async(AgentDefinition.objects.get)(slug=slug)
        config_dict = await sync_to_async(agent.to_config_dict)()
        config = AgentConfig.from_dict(config_dict)
        
        return cls(config, agent_id=str(agent.id))
    
    @classmethod
    async def from_id(cls, agent_id: str) -> "DatabaseAgentRuntime":
        """
        Load a runtime from the database by agent ID.
        
        Args:
            agent_id: The agent's UUID
            
        Returns:
            DatabaseAgentRuntime instance
            
        Raises:
            AgentDefinition.DoesNotExist: If agent not found
        """
        from django_agent_runtime.models import AgentDefinition
        
        agent = await sync_to_async(AgentDefinition.objects.get)(id=agent_id)
        config_dict = await sync_to_async(agent.to_config_dict)()
        config = AgentConfig.from_dict(config_dict)
        
        return cls(config, agent_id=str(agent.id))
    
    @classmethod
    async def from_revision(
        cls, 
        agent_slug: str, 
        revision_number: int
    ) -> "DatabaseAgentRuntime":
        """
        Load a runtime from a specific revision.
        
        This allows running an agent with a historical configuration.
        
        Args:
            agent_slug: The agent's slug
            revision_number: The revision number to load
            
        Returns:
            DatabaseAgentRuntime instance
            
        Raises:
            AgentDefinition.DoesNotExist: If agent not found
            AgentRevision.DoesNotExist: If revision not found
        """
        from django_agent_runtime.models import AgentDefinition, AgentRevision
        
        agent = await sync_to_async(AgentDefinition.objects.get)(slug=agent_slug)
        revision = await sync_to_async(
            agent.revisions.get
        )(revision_number=revision_number)
        
        config = AgentConfig.from_dict(revision.content)
        
        return cls(config, agent_id=str(agent.id))
    
    @classmethod
    def from_config_dict(cls, config_dict: dict, agent_id: Optional[str] = None) -> "DatabaseAgentRuntime":
        """
        Create a runtime from a config dictionary.

        Useful when you already have the config dict (e.g., from a revision).

        Args:
            config_dict: The configuration dictionary
            agent_id: Optional database ID

        Returns:
            DatabaseAgentRuntime instance
        """
        config = AgentConfig.from_dict(config_dict)
        return cls(config, agent_id=agent_id)

    @classmethod
    def from_agent(cls, agent) -> "DatabaseAgentRuntime":
        """
        Create a runtime from an AgentDefinition instance (sync).

        This is a synchronous method for use in contexts where async
        is not available (e.g., registry loading).

        Args:
            agent: The AgentDefinition model instance

        Returns:
            DatabaseAgentRuntime instance
        """
        config_dict = agent.to_config_dict()
        config = AgentConfig.from_dict(config_dict)

        logger.info(f"Loaded agent runtime from database: {agent.slug}")
        return cls(config, agent_id=str(agent.id))

