"""
Django Agent Runtime - Production-grade AI agent execution for Django.

Framework-agnostic • Model-agnostic • Production-grade concurrency

This package provides:
- AgentRun model for tracking agent executions
- Queue adapters (Postgres, Redis Streams) for job distribution
- Event bus for real-time streaming to UI
- Plugin system for custom agent runtimes
- LLM client abstraction (provider-agnostic)
- Persistence layer (memory, conversations, tasks, preferences)
- Optional integrations (LiteLLM, Langfuse)

Usage:
    1. Add 'django_agent_runtime' to INSTALLED_APPS
    2. Configure DJANGO_AGENT_RUNTIME settings
    3. Run migrations
    4. Start workers: ./manage.py runagent
"""

__version__ = "0.3.0"

default_app_config = "django_agent_runtime.apps.DjangoAgentRuntimeConfig"

