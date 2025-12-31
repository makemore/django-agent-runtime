"""
Django app configuration for django_agent_runtime.
"""

from django.apps import AppConfig


class DjangoAgentRuntimeConfig(AppConfig):
    """Configuration for the Django Agent Runtime app."""

    name = "django_agent_runtime"
    verbose_name = "Django Agent Runtime"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self):
        """
        Called when Django starts. Used to:
        - Auto-discover agent runtime plugins
        - Register signal handlers
        - Validate configuration
        """
        from django_agent_runtime.runtime.registry import autodiscover_runtimes

        # Auto-discover runtimes from entry points and settings
        autodiscover_runtimes()

