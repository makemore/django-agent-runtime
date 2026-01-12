"""
API module for django_agent_runtime.

Provides base ViewSets for agent runtime API. Inherit from these
in your project and set your own permission_classes.

Example:
    from django_agent_runtime.api.views import BaseAgentRunViewSet
    
    class AgentRunViewSet(BaseAgentRunViewSet):
        permission_classes = [IsAuthenticated]
"""

from django_agent_runtime.api.views import (
    BaseAgentRunViewSet,
    BaseAgentConversationViewSet,
    sync_event_stream,
    async_event_stream,
)

__all__ = [
    "BaseAgentRunViewSet",
    "BaseAgentConversationViewSet",
    "sync_event_stream",
    "async_event_stream",
]
