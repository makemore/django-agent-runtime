"""
Helper functions for configuring persistence in Django.

Provides convenient ways to get a PersistenceManager configured
with Django-backed stores for the current request/user.
"""

from typing import Optional

from agent_runtime_core.persistence import (
    PersistenceConfig,
    PersistenceManager,
)

from django_agent_runtime.persistence.stores import (
    DjangoMemoryStore,
    DjangoConversationStore,
    DjangoTaskStore,
    DjangoPreferencesStore,
    DjangoKnowledgeStore,
    DjangoAuditStore,
)


def get_persistence_config(user) -> PersistenceConfig:
    """
    Get a PersistenceConfig configured with Django stores for a user.

    Args:
        user: Django user instance

    Returns:
        PersistenceConfig with all Django stores configured

    Example:
        from django_agent_runtime.persistence import get_persistence_config
        from agent_runtime_core.persistence import PersistenceManager

        config = get_persistence_config(request.user)
        manager = PersistenceManager(config)

        # Use the manager
        await manager.memory.set("key", "value")
    """
    return PersistenceConfig(
        memory_store=DjangoMemoryStore(user=user),
        conversation_store=DjangoConversationStore(user=user),
        task_store=DjangoTaskStore(user=user),
        preferences_store=DjangoPreferencesStore(user=user),
        knowledge_store=DjangoKnowledgeStore(user=user),
        audit_store=DjangoAuditStore(user=user),
    )


def get_persistence_manager(user) -> PersistenceManager:
    """
    Get a PersistenceManager configured with Django stores for a user.
    
    This is a convenience function that creates both the config and manager.
    
    Args:
        user: Django user instance
        
    Returns:
        PersistenceManager ready to use
        
    Example:
        from django_agent_runtime.persistence import get_persistence_manager
        
        async def my_view(request):
            manager = get_persistence_manager(request.user)
            
            # Store memory
            await manager.memory.set("last_query", "hello world")
            
            # Get preferences
            theme = await manager.preferences.get("theme")
    """
    config = get_persistence_config(user)
    return PersistenceManager(config)


class PersistenceMiddleware:
    """
    Django middleware that attaches a PersistenceManager to the request.
    
    Add to MIDDLEWARE in settings.py:
        MIDDLEWARE = [
            ...
            'django_agent_runtime.persistence.helpers.PersistenceMiddleware',
        ]
    
    Then access in views:
        async def my_view(request):
            await request.persistence.memory.set("key", "value")
    
    Note: Only works for authenticated users. For anonymous users,
    request.persistence will be None.
    """
    
    def __init__(self, get_response):
        self.get_response = get_response
    
    def __call__(self, request):
        # Attach persistence manager for authenticated users
        if hasattr(request, 'user') and request.user.is_authenticated:
            request.persistence = get_persistence_manager(request.user)
        else:
            request.persistence = None
        
        response = self.get_response(request)
        return response


def get_store_factories(user_getter):
    """
    Get factory functions for lazy store instantiation.

    Useful when you need to defer user resolution (e.g., in class-based views).

    Args:
        user_getter: Callable that returns the current user

    Returns:
        Dict of factory functions suitable for PersistenceConfig

    Example:
        from django_agent_runtime.persistence.helpers import get_store_factories

        # In a class-based view
        factories = get_store_factories(lambda: self.request.user)
        config = PersistenceConfig(
            memory_store_factory=factories['memory'],
            conversation_store_factory=factories['conversation'],
            task_store_factory=factories['task'],
            preferences_store_factory=factories['preferences'],
            knowledge_store_factory=factories['knowledge'],
            audit_store_factory=factories['audit'],
        )
    """
    return {
        'memory': lambda: DjangoMemoryStore(user=user_getter()),
        'conversation': lambda: DjangoConversationStore(user=user_getter()),
        'task': lambda: DjangoTaskStore(user=user_getter()),
        'preferences': lambda: DjangoPreferencesStore(user=user_getter()),
        'knowledge': lambda: DjangoKnowledgeStore(user=user_getter()),
        'audit': lambda: DjangoAuditStore(user=user_getter()),
    }
