"""
URL configuration for django_agent_runtime.

Include these URLs in your project's urls.py:

    from django.urls import path, include

    urlpatterns = [
        ...
        path('api/agent-runtime/', include('django_agent_runtime.urls')),
    ]
"""

from django.urls import path, include
from rest_framework.routers import DefaultRouter

from django_agent_runtime.api.views import (
    AgentRunViewSet,
    AgentConversationViewSet,
    async_event_stream,
)

app_name = "agent_runtime"

# DRF router for viewsets
router = DefaultRouter()
router.register(r"conversations", AgentConversationViewSet, basename="conversation")
router.register(r"runs", AgentRunViewSet, basename="run")

urlpatterns = [
    # REST API endpoints
    path("", include(router.urls)),
    # Async SSE endpoint (for ASGI deployments)
    path("runs/<str:run_id>/stream/", async_event_stream, name="run-stream"),
]

