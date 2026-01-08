"""
URL configuration for tests.

Includes the django_agent_runtime URLs with the proper namespace.
"""

from django.urls import path, include

urlpatterns = [
    path("", include("django_agent_runtime.urls", namespace="agent_runtime")),
]

