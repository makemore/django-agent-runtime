"""
Django models for the Agent Runtime.

Provides:
- AgentConversation: Groups related runs
- AgentRun: Individual agent execution
- AgentEvent: Append-only event log
- AgentCheckpoint: State snapshots for recovery
- Persistence models: Memory, Conversation, Message, Task, Preferences
"""

from django_agent_runtime.models.base import (
    AbstractAgentConversation,
    AbstractAgentRun,
    AbstractAgentEvent,
    AbstractAgentCheckpoint,
)
from django_agent_runtime.models.concrete import (
    AgentConversation,
    AgentRun,
    AgentEvent,
    AgentCheckpoint,
)

# Import persistence models so Django can discover them
from django_agent_runtime.persistence.models import (
    Memory,
    PersistenceConversation,
    PersistenceMessage,
    PersistenceTaskList,
    PersistenceTask,
    Preferences,
)

__all__ = [
    # Abstract models (for custom implementations)
    "AbstractAgentConversation",
    "AbstractAgentRun",
    "AbstractAgentEvent",
    "AbstractAgentCheckpoint",
    # Concrete models (default implementation)
    "AgentConversation",
    "AgentRun",
    "AgentEvent",
    "AgentCheckpoint",
    # Persistence models
    "Memory",
    "PersistenceConversation",
    "PersistenceMessage",
    "PersistenceTaskList",
    "PersistenceTask",
    "Preferences",
]

