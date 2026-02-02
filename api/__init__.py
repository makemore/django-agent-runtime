"""
API module for django_agent_runtime.

Provides base ViewSets for agent runtime API. Inherit from these
in your project and set your own permission_classes.

Example:
    from django_agent_runtime.api.views import BaseAgentRunViewSet

    class AgentRunViewSet(BaseAgentRunViewSet):
        permission_classes = [IsAuthenticated]

Note: We use lazy imports to avoid circular dependencies during Django startup.
Views import models which require apps to be ready, but permissions don't.
"""


def __getattr__(name):
    """Lazy import to avoid circular dependencies during settings loading."""
    if name in ("BaseAgentRunViewSet", "BaseAgentConversationViewSet",
                "sync_event_stream", "async_event_stream", "BaseAgentFileViewSet"):
        from django_agent_runtime.api import views
        return getattr(views, name)

    if name in ("AnonymousSessionAuthentication", "IsAuthenticatedOrAnonymousSession",
                "get_anonymous_session"):
        from django_agent_runtime.api import permissions
        return getattr(permissions, name)

    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "BaseAgentRunViewSet",
    "BaseAgentConversationViewSet",
    "BaseAgentFileViewSet",
    "sync_event_stream",
    "async_event_stream",
    "AnonymousSessionAuthentication",
    "IsAuthenticatedOrAnonymousSession",
    "get_anonymous_session",
]
