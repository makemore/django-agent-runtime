"""
Concrete model implementations for the Agent Runtime.

These are the default models used when no custom models are configured.
Host projects can use these directly or create their own by extending the abstract models.
"""

from django.db import models

from django_agent_runtime.models.base import (
    AbstractAgentConversation,
    AbstractAgentRun,
    AbstractAgentEvent,
    AbstractAgentCheckpoint,
)


class AgentConversation(AbstractAgentConversation):
    """
    Default concrete implementation of AgentConversation.

    Groups related agent runs into a conversation.

    For anonymous session support, create your own model::

        from django.db import models
        from django_agent_runtime.models.base import AbstractAgentConversation

        class MyAgentConversation(AbstractAgentConversation):
            anonymous_session = models.ForeignKey(
                "myapp.MySession",
                on_delete=models.SET_NULL,
                null=True,
                blank=True,
                related_name="agent_conversations",
            )

            class Meta(AbstractAgentConversation.Meta):
                abstract = False

    Then configure in settings::

        DJANGO_AGENT_RUNTIME = {
            'CONVERSATION_MODEL': 'myapp.MyAgentConversation',
        }
    """

    class Meta(AbstractAgentConversation.Meta):
        abstract = False
        db_table = "agent_runtime_conversation"


class AgentRun(AbstractAgentRun):
    """
    Default concrete implementation of AgentRun.

    Tracks individual agent executions with full lifecycle management.
    """

    conversation = models.ForeignKey(
        AgentConversation,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="runs",
    )

    class Meta(AbstractAgentRun.Meta):
        abstract = False
        db_table = "agent_runtime_run"


class AgentEvent(AbstractAgentEvent):
    """
    Default concrete implementation of AgentEvent.

    Append-only event log for streaming to UI.
    """

    run = models.ForeignKey(
        AgentRun,
        on_delete=models.CASCADE,
        related_name="events",
    )

    class Meta(AbstractAgentEvent.Meta):
        abstract = False
        db_table = "agent_runtime_event"
        unique_together = [("run", "seq")]


class AgentCheckpoint(AbstractAgentCheckpoint):
    """
    Default concrete implementation of AgentCheckpoint.

    State snapshots for recovery from failures.
    """

    run = models.ForeignKey(
        AgentRun,
        on_delete=models.CASCADE,
        related_name="checkpoints",
    )

    class Meta(AbstractAgentCheckpoint.Meta):
        abstract = False
        db_table = "agent_runtime_checkpoint"
        unique_together = [("run", "seq")]

