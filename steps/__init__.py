"""
Django-specific step execution with ORM checkpoint persistence.

This module provides Django-enhanced versions of the step execution
primitives from agent_runtime_core.steps:

- DjangoStepExecutor: StepExecutor with Django ORM checkpointing
- DjangoRunContext: RunContext implementation using Django's cache and ORM

Example:
    from django_agent_runtime.steps import DjangoStepExecutor, DjangoRunContext
    from agent_runtime_core.steps import Step

    # Create a run context
    ctx = DjangoRunContext(run_id=run_id, user=request.user)

    # Create executor and run steps
    executor = DjangoStepExecutor(ctx)
    results = await executor.run([
        Step("fetch", fetch_data),
        Step("process", process_data, retries=3),
        Step("save", save_results),
    ])
"""

from django_agent_runtime.steps.context import DjangoRunContext
from django_agent_runtime.steps.executor import DjangoStepExecutor
from django_agent_runtime.steps.models import (
    StepCheckpoint,
    StepEvent,
    StepStatusChoices,
    StepEventTypeChoices,
)

__all__ = [
    "DjangoRunContext",
    "DjangoStepExecutor",
    "StepCheckpoint",
    "StepEvent",
    "StepStatusChoices",
    "StepEventTypeChoices",
]

