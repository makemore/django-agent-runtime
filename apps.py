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
        - Configure core runtime with Django settings
        """
        from django_agent_runtime.runtime.registry import autodiscover_runtimes
        from django_agent_runtime.conf import is_debug
        from agent_runtime_core import configure as configure_core

        # Sync Django's debug setting to core runtime
        # This enables cost/context tracking in debug mode
        configure_core(debug=is_debug())

        # Auto-discover runtimes from entry points and settings
        autodiscover_runtimes()

