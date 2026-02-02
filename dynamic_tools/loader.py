"""
Tool Loader for loading tools from database into ToolRegistry.

Loads static AgentTools, DynamicTools, and SubAgentTools for an agent.
"""

import logging
from typing import Optional
from uuid import UUID

from asgiref.sync import sync_to_async
from agent_runtime_core import Tool, ToolRegistry
from agent_runtime_core.multi_agent import (
    AgentTool as AgentToolCore,
    InvocationMode,
    ContextMode,
    invoke_agent,
)

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

        # Load sub-agent tools (SubAgentTool)
        sub_agent_tools = await self._load_sub_agent_tools(agent, agent_run_id)
        for tool in sub_agent_tools:
            registry.register(tool)

        logger.info(
            f"Loaded {len(static_tools)} static, {len(dynamic_tools)} dynamic, "
            f"and {len(sub_agent_tools)} sub-agent tools for agent {agent_slug}"
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

    async def _load_sub_agent_tools(
        self,
        agent,
        parent_run_id: Optional[UUID],
    ) -> list[Tool]:
        """
        Load SubAgentTool definitions and create executable tools.

        Sub-agent tools allow one agent to delegate to another agent.
        The handler invokes the sub-agent using invoke_agent() from
        agent_runtime_core.multi_agent.

        Args:
            agent: The parent agent definition
            parent_run_id: The parent agent's run ID for tracing

        Returns:
            List of Tool objects for each active sub-agent tool
        """
        tools = []

        sub_agent_tools = await self._get_sub_agent_tools(agent)

        for sub_agent_tool in sub_agent_tools:
            tool = self._create_sub_agent_tool(sub_agent_tool, parent_run_id)
            tools.append(tool)

        return tools

    @sync_to_async
    def _get_sub_agent_tools(self, agent) -> list:
        """Get sub-agent tools for an agent."""
        return list(
            agent.sub_agent_tools.filter(is_active=True).select_related('sub_agent')
        )

    def _create_sub_agent_tool(
        self,
        sub_agent_tool,
        parent_run_id: Optional[UUID],
    ) -> Tool:
        """
        Create an executable Tool from a SubAgentTool model.

        The handler captures the sub-agent's slug and context_mode, then
        at execution time:
        1. Gets the sub-agent's runtime using get_runtime_async()
        2. Creates an AgentTool wrapper
        3. Calls invoke_agent() with the parent context

        The handler expects to receive 'ctx' as a keyword argument containing
        the parent's RunContext. This is passed by the tool execution layer
        when metadata['requires_context'] is True.
        """
        # Capture values for the closure
        sub_agent_slug = sub_agent_tool.sub_agent.slug
        tool_name = sub_agent_tool.name
        tool_description = sub_agent_tool.description
        context_mode_str = sub_agent_tool.context_mode

        # Map Django context_mode to core ContextMode enum
        context_mode_map = {
            'message_only': ContextMode.MESSAGE_ONLY,
            'summary': ContextMode.SUMMARY,
            'full': ContextMode.FULL,
        }
        context_mode = context_mode_map.get(context_mode_str, ContextMode.MESSAGE_ONLY)

        async def handler(message: str, context: Optional[str] = None, **kwargs) -> dict:
            """
            Handler that invokes the sub-agent.

            Args:
                message: The message/task to send to the sub-agent
                context: Optional additional context
                **kwargs: May contain 'ctx' (RunContext) if requires_context=True

            Returns:
                Dict with response from sub-agent
            """
            # Get the parent context from kwargs
            # This is passed by the tool execution layer when requires_context=True
            parent_ctx = kwargs.get('ctx')
            if parent_ctx is None:
                logger.error(
                    f"Sub-agent tool '{tool_name}' called without parent context. "
                    "Ensure the tool execution passes ctx to the handler."
                )
                return {
                    "error": "Sub-agent tool requires parent context",
                    "tool": tool_name,
                }

            try:
                # Get the sub-agent's runtime
                from django_agent_runtime.runtime.registry import get_runtime_async
                sub_agent_runtime = await get_runtime_async(sub_agent_slug)

                # Create an AgentTool wrapper for the sub-agent
                agent_tool = AgentToolCore(
                    agent=sub_agent_runtime,
                    name=tool_name,
                    description=tool_description,
                    invocation_mode=InvocationMode.DELEGATE,  # Always delegate for now
                    context_mode=context_mode,
                    metadata={
                        'sub_agent_slug': sub_agent_slug,
                        'parent_run_id': str(parent_run_id) if parent_run_id else None,
                    },
                )

                # Get conversation history from parent context
                conversation_history = list(parent_ctx.input_messages)

                # Invoke the sub-agent
                result = await invoke_agent(
                    agent_tool=agent_tool,
                    message=message,
                    parent_ctx=parent_ctx,
                    conversation_history=conversation_history,
                    additional_context=context,
                )

                logger.info(
                    f"Sub-agent '{sub_agent_slug}' completed for tool '{tool_name}'"
                )

                return {
                    "response": result.response,
                    "sub_agent": result.sub_agent_key,
                    "handoff": result.handoff,
                }

            except KeyError as e:
                logger.error(f"Sub-agent not found: {sub_agent_slug} - {e}")
                return {
                    "error": f"Sub-agent not found: {sub_agent_slug}",
                    "tool": tool_name,
                }
            except Exception as e:
                logger.exception(f"Error invoking sub-agent '{sub_agent_slug}'")
                return {
                    "error": str(e),
                    "tool": tool_name,
                    "sub_agent": sub_agent_slug,
                }

        # Standard schema for sub-agent tools: message + optional context
        parameters = {
            'type': 'object',
            'properties': {
                'message': {
                    'type': 'string',
                    'description': 'The message or task to send to this agent',
                },
                'context': {
                    'type': 'string',
                    'description': 'Optional additional context to include',
                },
            },
            'required': ['message'],
        }

        return Tool(
            name=tool_name,
            description=tool_description,
            parameters=parameters,
            handler=handler,
            has_side_effects=True,  # Sub-agent invocations have side effects
            requires_confirmation=False,
            metadata={
                'tool_type': 'sub_agent',
                'sub_agent_slug': sub_agent_slug,
                'context_mode': context_mode_str,
                'requires_context': True,  # Signal that handler needs ctx
                'sub_agent_tool_id': str(sub_agent_tool.id),
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

