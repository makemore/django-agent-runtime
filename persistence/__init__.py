"""
Django persistence layer for agent-runtime-core.

This module provides Django-backed implementations of the persistence stores
defined in agent_runtime_core.persistence.

Usage:
    from django_agent_runtime.persistence import (
        DjangoMemoryStore,
        DjangoConversationStore,
        DjangoTaskStore,
        DjangoPreferencesStore,
        DjangoKnowledgeStore,
        DjangoAuditStore,
        get_persistence_manager,
    )

    # In a view or middleware
    manager = get_persistence_manager(request.user)

    # Or configure manually
    from agent_runtime_core.persistence import PersistenceConfig, PersistenceManager

    config = PersistenceConfig(
        memory_store=DjangoMemoryStore(user=request.user),
        conversation_store=DjangoConversationStore(user=request.user),
        task_store=DjangoTaskStore(user=request.user),
        preferences_store=DjangoPreferencesStore(user=request.user),
        knowledge_store=DjangoKnowledgeStore(user=request.user),
        audit_store=DjangoAuditStore(user=request.user),
    )
    manager = PersistenceManager(config)
"""

from django_agent_runtime.persistence.stores import (
    DjangoMemoryStore,
    DjangoConversationStore,
    DjangoTaskStore,
    DjangoPreferencesStore,
    DjangoKnowledgeStore,
    DjangoAuditStore,
)
from django_agent_runtime.persistence.helpers import (
    get_persistence_manager,
    get_persistence_config,
)

__all__ = [
    # Store implementations
    "DjangoMemoryStore",
    "DjangoConversationStore",
    "DjangoTaskStore",
    "DjangoPreferencesStore",
    "DjangoKnowledgeStore",
    "DjangoAuditStore",
    # Helpers
    "get_persistence_manager",
    "get_persistence_config",
]

