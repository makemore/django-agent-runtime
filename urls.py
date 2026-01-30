"""
URL configuration for django_agent_runtime.

Include these URLs in your project's urls.py:

    from django.urls import path, include

    urlpatterns = [
        path("agent/", include("django_agent_runtime.urls", namespace="agent_runtime")),
    ]

Note: The viewsets provided are base classes. For production use, you should
create your own viewsets that inherit from these and set appropriate
authentication_classes and permission_classes.
"""

from django.urls import path, include
from rest_framework.routers import DefaultRouter

from django_agent_runtime.api.views import (
    BaseAgentConversationViewSet,
    BaseAgentFileViewSet,
    BaseAgentRunViewSet,
    BaseAgentTaskListViewSet,
    BaseModelsViewSet,
    sync_event_stream,
)

app_name = "django_agent_runtime"

# Create router for viewsets
router = DefaultRouter()
router.register(r"conversations", BaseAgentConversationViewSet, basename="conversation")
router.register(r"files", BaseAgentFileViewSet, basename="file")
router.register(r"runs", BaseAgentRunViewSet, basename="run")
router.register(r"tasks", BaseAgentTaskListViewSet, basename="task")
router.register(r"models", BaseModelsViewSet, basename="models")

urlpatterns = [
    # ViewSet routes
    path("", include(router.urls)),
    # SSE streaming endpoint
    path("runs/<str:run_id>/events/", sync_event_stream, name="run_events"),
]

