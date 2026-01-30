"""
Django models for the Agent Runtime.

Provides:
- AgentConversation: Groups related runs
- AgentRun: Individual agent execution
- AgentEvent: Append-only event log
- AgentCheckpoint: State snapshots for recovery
- Persistence models: Memory, Conversation, Message, Task, Preferences
- Agent Definition models: AgentDefinition, AgentVersion, AgentTool, AgentKnowledge
"""

from django_agent_runtime.models.base import (
    AbstractAgentConversation,
    AbstractAgentRun,
    AbstractAgentEvent,
    AbstractAgentCheckpoint,
    AbstractAgentFile,
    AbstractAgentTaskList,
    AbstractAgentTask,
    TaskState,
)
from django_agent_runtime.models.concrete import (
    AgentConversation,
    AgentRun,
    AgentEvent,
    AgentCheckpoint,
    AgentFile,
    AgentTaskList,
    AgentTask,
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

# Import agent definition models
from django_agent_runtime.models.definitions import (
    AgentDefinition,
    AgentVersion,
    AgentRevision,
    AgentTool,
    AgentKnowledge,
    DiscoveredFunction,
    DynamicTool,
    DynamicToolExecution,
    # Sub-agent tool model
    SubAgentTool,
    # Multi-agent system models
    AgentSystem,
    AgentSystemMember,
    AgentSystemVersion,
    AgentSystemSnapshot,
    # Spec document models
    SpecDocument,
    SpecDocumentVersion,
    # Collaborator models for multi-user access
    CollaboratorRole,
    AgentCollaborator,
    SystemCollaborator,
)

# Import step execution models
from django_agent_runtime.steps.models import (
    StepCheckpoint,
    StepEvent,
    StepStatusChoices,
    StepEventTypeChoices,
)

__all__ = [
    # Abstract models (for custom implementations)
    "AbstractAgentConversation",
    "AbstractAgentRun",
    "AbstractAgentEvent",
    "AbstractAgentCheckpoint",
    "AbstractAgentFile",
    "AbstractAgentTaskList",
    "AbstractAgentTask",
    "TaskState",
    # Concrete models (default implementation)
    "AgentConversation",
    "AgentRun",
    "AgentEvent",
    "AgentCheckpoint",
    "AgentFile",
    "AgentTaskList",
    "AgentTask",
    # Persistence models
    "Memory",
    "PersistenceConversation",
    "PersistenceMessage",
    "PersistenceTaskList",
    "PersistenceTask",
    "Preferences",
    # Agent Definition models
    "AgentDefinition",
    "AgentVersion",
    "AgentRevision",
    "AgentTool",
    "AgentKnowledge",
    # Dynamic Tool models
    "DiscoveredFunction",
    "DynamicTool",
    "DynamicToolExecution",
    # Sub-agent tool model
    "SubAgentTool",
    # Multi-agent system models
    "AgentSystem",
    "AgentSystemMember",
    "AgentSystemVersion",
    "AgentSystemSnapshot",
    # Spec document models
    "SpecDocument",
    "SpecDocumentVersion",
    # Collaborator models for multi-user access
    "CollaboratorRole",
    "AgentCollaborator",
    "SystemCollaborator",
    # Step execution models
    "StepCheckpoint",
    "StepEvent",
    "StepStatusChoices",
    "StepEventTypeChoices",
]

