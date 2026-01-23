"""
Django-specific tool utilities.

Provides decorators and helpers for creating tools that work seamlessly
with Django's ORM and async/sync boundaries.
"""

import functools
import inspect
from typing import Any, Callable, Optional

from asgiref.sync import sync_to_async
from agent_runtime_core import Tool


def django_tool(
    name: str,
    description: str,
    parameters: dict,
    has_side_effects: bool = False,
    requires_confirmation: bool = False,
    metadata: Optional[dict] = None,
):
    """
    Decorator for creating Django tools with automatic sync_to_async wrapping.
    
    This decorator eliminates the boilerplate of wrapping Django ORM calls
    in sync_to_async. Just write your tool function using Django's ORM
    normally, and the decorator handles the async conversion.
    
    Args:
        name: Tool name
        description: Tool description for the LLM
        parameters: JSON Schema for parameters
        has_side_effects: Whether the tool modifies data
        requires_confirmation: Whether to ask user before executing
        metadata: Additional metadata
    
    Returns:
        Tool object ready to register
    
    Example:
        @django_tool(
            name="get_client",
            description="Get client details by ID",
            parameters={
                "type": "object",
                "properties": {
                    "client_id": {"type": "integer", "description": "Client ID"}
                },
                "required": ["client_id"]
            }
        )
        def get_client(client_id: int) -> dict:
            # Use Django ORM directly - no sync_to_async needed!
            client = Client.objects.get(id=client_id)
            return {
                "id": client.id,
                "name": client.full_name,
                "email": client.email,
            }
        
        # Register the tool
        registry.register(get_client)
    """
    def decorator(func: Callable) -> Tool:
        # Check if function is already async
        if inspect.iscoroutinefunction(func):
            # Already async, use as-is
            handler = func
        else:
            # Sync function, wrap in sync_to_async
            # Use thread_sensitive=False to run in a thread pool, avoiding
            # CurrentThreadExecutor conflicts when called from sync views
            # using loop.run_until_complete()
            handler = sync_to_async(func, thread_sensitive=False)
        
        # Create the Tool object
        tool = Tool(
            name=name,
            description=description,
            parameters=parameters,
            handler=handler,
            has_side_effects=has_side_effects,
            requires_confirmation=requires_confirmation,
            metadata=metadata or {},
        )
        
        # Store original function for testing/introspection
        tool.metadata['original_function'] = func
        tool.metadata['is_django_tool'] = True
        
        return tool
    
    return decorator


def django_tool_with_context(
    name: str,
    description: str,
    parameters: dict,
    has_side_effects: bool = False,
    requires_confirmation: bool = False,
    metadata: Optional[dict] = None,
):
    """
    Decorator for Django tools that need access to the RunContext.
    
    Similar to django_tool, but the decorated function receives the
    RunContext as the first argument, allowing access to metadata,
    user information, etc.
    
    Args:
        name: Tool name
        description: Tool description for the LLM
        parameters: JSON Schema for parameters
        has_side_effects: Whether the tool modifies data
        requires_confirmation: Whether to ask user before executing
        metadata: Additional metadata
    
    Returns:
        Tool object ready to register
    
    Example:
        @django_tool_with_context(
            name="get_my_clients",
            description="Get clients for the current user",
            parameters={"type": "object", "properties": {}}
        )
        def get_my_clients(ctx: RunContext) -> dict:
            # Access user from context
            user_id = ctx.metadata.get('user_id')
            user = User.objects.get(id=user_id)
            
            # Use Django ORM
            clients = Client.objects.filter(firm_member__profile__user=user)
            return {
                "count": clients.count(),
                "clients": [{"id": c.id, "name": c.full_name} for c in clients]
            }
    """
    def decorator(func: Callable) -> Tool:
        # The handler needs to extract ctx and pass remaining args to func
        if inspect.iscoroutinefunction(func):
            # Already async
            async def handler(ctx=None, **kwargs):
                if ctx is None:
                    raise ValueError(f"Tool {name} requires RunContext but none provided")
                return await func(ctx, **kwargs)
        else:
            # Sync function, wrap in sync_to_async
            # Use thread_sensitive=False to run in a thread pool, avoiding
            # CurrentThreadExecutor conflicts when called from sync views
            # using loop.run_until_complete()
            @functools.wraps(func)
            async def handler(ctx=None, **kwargs):
                if ctx is None:
                    raise ValueError(f"Tool {name} requires RunContext but none provided")
                return await sync_to_async(func, thread_sensitive=False)(ctx, **kwargs)
        
        # Create the Tool object
        tool = Tool(
            name=name,
            description=description,
            parameters=parameters,
            handler=handler,
            has_side_effects=has_side_effects,
            requires_confirmation=requires_confirmation,
            metadata=metadata or {},
        )
        
        # Store original function for testing/introspection
        tool.metadata['original_function'] = func
        tool.metadata['is_django_tool'] = True
        tool.metadata['requires_context'] = True
        
        return tool
    
    return decorator


__all__ = [
    'django_tool',
    'django_tool_with_context',
]
