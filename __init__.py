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
- Step execution with ORM checkpointing (DjangoStepExecutor)
- Optional integrations (LiteLLM, Langfuse)

Usage:
    1. Add 'django_agent_runtime' to INSTALLED_APPS
    2. Configure DJANGO_AGENT_RUNTIME settings
    3. Run migrations
    4. Start workers: ./manage.py runagent

Step Execution Example:
    from django_agent_runtime.steps import DjangoStepExecutor, DjangoRunContext
    from agent_runtime_core.steps import Step

    ctx = DjangoRunContext(run_id=run_id, user=request.user)
    executor = DjangoStepExecutor(ctx)
    results = await executor.run([
        Step("fetch", fetch_data),
        Step("process", process_data, retries=3),
    ])
"""

__version__ = "0.4.1"

default_app_config = "django_agent_runtime.apps.DjangoAgentRuntimeConfig"


# Convenience imports for step execution
def __getattr__(name):
    """Lazy imports to avoid Django app registry issues."""
    if name == "DjangoStepExecutor":
        from django_agent_runtime.steps.executor import DjangoStepExecutor
        return DjangoStepExecutor
    elif name == "DjangoRunContext":
        from django_agent_runtime.steps.context import DjangoRunContext
        return DjangoRunContext
    elif name == "StepCheckpoint":
        from django_agent_runtime.steps.models import StepCheckpoint
        return StepCheckpoint
    elif name == "StepEvent":
        from django_agent_runtime.steps.models import StepEvent
        return StepEvent
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

