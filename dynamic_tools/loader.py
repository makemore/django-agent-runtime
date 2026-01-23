"""
Tool Loader for loading tools from database into ToolRegistry.

Loads both static AgentTools and DynamicTools for an agent.
"""

import logging
from typing import Optional
from uuid import UUID

from asgiref.sync import sync_to_async
from agent_runtime_core import Tool, ToolRegistry

from django_agent_runtime.dynamic_tools.executor import DynamicToolExecutor

logger = logging.getLogger(__name__)


class DynamicToolLoader:
    """
    Loads tools from the database for an agent.
    
    Handles:
    - Loading AgentTool definitions
    - Loading DynamicTool definitions
    - Creating executable Tool objects
    - Integrating with DynamicToolExecutor for dynamic tools
    """
    
    def __init__(
        self,
        executor: Optional[DynamicToolExecutor] = None,
    ):
        """
        Initialize the loader.
        
        Args:
            executor: DynamicToolExecutor for executing dynamic tools
        """
        self.executor = executor or DynamicToolExecutor()
    
    async def load_tools_for_agent(
        self,
        agent_slug: str,
        agent_run_id: Optional[UUID] = None,
        user_id: Optional[int] = None,
    ) -> ToolRegistry:
        """
        Load all tools for an agent into a ToolRegistry.
        
        Args:
            agent_slug: The agent's slug identifier
            agent_run_id: Optional run ID for audit logging
            user_id: Optional user ID for audit logging
            
        Returns:
            ToolRegistry populated with the agent's tools
        """
        registry = ToolRegistry()
        
        # Load agent definition
        agent = await self._get_agent(agent_slug)
        if not agent:
            logger.warning(f"Agent not found: {agent_slug}")
            return registry
        
        # Load static tools (AgentTool)
        static_tools = await self._load_static_tools(agent)
        for tool in static_tools:
            registry.register(tool)
        
        # Load dynamic tools (DynamicTool)
        dynamic_tools = await self._load_dynamic_tools(
            agent, agent_run_id, user_id
        )
        for tool in dynamic_tools:
            registry.register(tool)
        
        logger.info(
            f"Loaded {len(static_tools)} static and {len(dynamic_tools)} "
            f"dynamic tools for agent {agent_slug}"
        )
        
        return registry
    
    @sync_to_async
    def _get_agent(self, agent_slug: str):
        """Get agent definition by slug."""
        from django_agent_runtime.models import AgentDefinition
        
        try:
            return AgentDefinition.objects.get(slug=agent_slug, is_active=True)
        except AgentDefinition.DoesNotExist:
            return None
    
    @sync_to_async
    def _load_static_tools(self, agent) -> list[Tool]:
        """Load static AgentTool definitions."""
        tools = []
        
        for agent_tool in agent.tools.filter(is_active=True):
            # Create a placeholder handler for static tools
            # These would typically be resolved to actual implementations
            async def static_handler(**kwargs):
                return {"error": "Static tool handler not implemented"}
            
            tool = Tool(
                name=agent_tool.name,
                description=agent_tool.description,
                parameters=agent_tool.parameters_schema or {
                    'type': 'object',
                    'properties': {},
                },
                handler=static_handler,
                metadata={
                    'tool_type': agent_tool.tool_type,
                    'builtin_ref': agent_tool.builtin_ref,
                    'config': agent_tool.config,
                },
            )
            tools.append(tool)
        
        return tools
    
    async def _load_dynamic_tools(
        self,
        agent,
        agent_run_id: Optional[UUID],
        user_id: Optional[int],
    ) -> list[Tool]:
        """Load DynamicTool definitions and create executable tools."""
        tools = []
        
        dynamic_tools = await self._get_dynamic_tools(agent)
        
        for dynamic_tool in dynamic_tools:
            tool = self._create_dynamic_tool(
                dynamic_tool, agent_run_id, user_id
            )
            tools.append(tool)
        
        return tools
    
    @sync_to_async
    def _get_dynamic_tools(self, agent) -> list:
        """Get dynamic tools for an agent."""
        return list(agent.dynamic_tools.filter(is_active=True))
    
    def _create_dynamic_tool(
        self,
        dynamic_tool,
        agent_run_id: Optional[UUID],
        user_id: Optional[int],
    ) -> Tool:
        """Create an executable Tool from a DynamicTool model."""
        # Create handler that uses the executor
        async def handler(**kwargs):
            return await self.executor.execute(
                function_path=dynamic_tool.function_path,
                arguments=kwargs,
                timeout=dynamic_tool.timeout_seconds,
                agent_run_id=agent_run_id,
                user_id=user_id,
                tool_id=dynamic_tool.id,
            )
        
        return Tool(
            name=dynamic_tool.name,
            description=dynamic_tool.description,
            parameters=dynamic_tool.parameters_schema or {
                'type': 'object',
                'properties': {},
            },
            handler=handler,
            has_side_effects=not dynamic_tool.is_safe,
            requires_confirmation=dynamic_tool.requires_confirmation,
            metadata={
                'tool_type': 'dynamic',
                'function_path': dynamic_tool.function_path,
                'execution_mode': dynamic_tool.execution_mode,
                'is_verified': dynamic_tool.is_verified,
                'dynamic_tool_id': str(dynamic_tool.id),
            },
        )


# Singleton instance for convenience
_default_loader: Optional[DynamicToolLoader] = None


def get_tool_loader() -> DynamicToolLoader:
    """Get the default tool loader instance."""
    global _default_loader
    if _default_loader is None:
        _default_loader = DynamicToolLoader()
    return _default_loader


async def load_agent_tools(
    agent_slug: str,
    agent_run_id: Optional[UUID] = None,
    user_id: Optional[int] = None,
) -> ToolRegistry:
    """
    Convenience function to load tools for an agent.
    
    Args:
        agent_slug: The agent's slug identifier
        agent_run_id: Optional run ID for audit logging
        user_id: Optional user ID for audit logging
        
    Returns:
        ToolRegistry populated with the agent's tools
    """
    loader = get_tool_loader()
    return await loader.load_tools_for_agent(
        agent_slug, agent_run_id, user_id
    )

