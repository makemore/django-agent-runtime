"""
Django-specific StepExecutor with ORM checkpoint persistence.

Extends the base StepExecutor from agent-runtime-core with
Django-specific features like database checkpointing and
status tracking.
"""

from typing import Any, Optional
from uuid import UUID

from django.utils import timezone
from asgiref.sync import sync_to_async

from agent_runtime_core.steps import Step, StepExecutor, ExecutionState
from agent_runtime_core.interfaces import EventType

from django_agent_runtime.steps.models import (
    StepCheckpoint,
    StepStatusChoices,
)


class DjangoStepExecutor(StepExecutor):
    """
    Django-enhanced StepExecutor with database checkpoint persistence.
    
    This executor extends the base StepExecutor with:
    - Automatic database checkpointing via StepCheckpoint model
    - Status tracking (pending, running, completed, failed, cancelled)
    - Integration with Django's ORM for state persistence
    - Support for user-scoped checkpoints
    
    Example:
        from django_agent_runtime.steps import DjangoStepExecutor, DjangoRunContext
        from agent_runtime_core.steps import Step
        
        async def fetch_data(ctx, state):
            # Fetch data
            return {"data": "fetched"}
        
        async def process_data(ctx, state):
            # Process data
            return {"processed": True}
        
        ctx = DjangoRunContext(run_id=run_id, user=request.user)
        executor = DjangoStepExecutor(ctx)
        
        results = await executor.run([
            Step("fetch", fetch_data),
            Step("process", process_data, retries=3),
        ])
    """
    
    def __init__(
        self,
        ctx,
        *,
        checkpoint_key: str = "_step_executor_state",
        cancel_check_interval: float = 0.5,
        auto_update_status: bool = True,
    ):
        """
        Initialize the Django step executor.
        
        Args:
            ctx: DjangoRunContext instance
            checkpoint_key: Key used for storing execution state
            cancel_check_interval: How often to check for cancellation
            auto_update_status: Whether to automatically update checkpoint status
        """
        super().__init__(
            ctx,
            checkpoint_key=checkpoint_key,
            cancel_check_interval=cancel_check_interval,
        )
        self.auto_update_status = auto_update_status
        self._checkpoint: Optional[StepCheckpoint] = None
    
    async def run(
        self,
        steps: list[Step],
        *,
        initial_state: Optional[dict] = None,
        resume: bool = True,
    ) -> dict[str, Any]:
        """
        Execute a sequence of steps with Django ORM checkpointing.
        
        This method wraps the base run() to add status tracking
        and error handling specific to Django.
        """
        try:
            # Update status to running
            if self.auto_update_status:
                await self._update_status(StepStatusChoices.RUNNING)
            
            # Run the steps
            results = await super().run(
                steps,
                initial_state=initial_state,
                resume=resume,
            )
            
            # Update status to completed
            if self.auto_update_status:
                await self._update_status(
                    StepStatusChoices.COMPLETED,
                    completed_at=timezone.now(),
                )
            
            return results
            
        except Exception as e:
            # Update status to failed
            if self.auto_update_status:
                error_msg = str(e)
                if self.ctx.cancelled():
                    await self._update_status(StepStatusChoices.CANCELLED)
                else:
                    await self._update_status(
                        StepStatusChoices.FAILED,
                        last_error=error_msg,
                    )
            raise
    
    async def _load_state(self) -> Optional[ExecutionState]:
        """Load execution state from Django database."""
        try:
            checkpoint = await sync_to_async(
                StepCheckpoint.objects.filter(
                    run_id=self.ctx.run_id,
                    checkpoint_key=self.checkpoint_key,
                ).first
            )()
            
            if checkpoint:
                self._checkpoint = checkpoint
                state_dict = checkpoint.to_execution_state_dict()
                return ExecutionState.from_dict(state_dict)
        except Exception:
            pass
        
        return None
    
    async def _save_state(self) -> None:
        """Save execution state to Django database."""
        if self._state is None:
            return
        
        state_dict = self._state.to_dict()
        
        # Get user from context if available
        user = getattr(self.ctx, 'user', None)
        conversation_id = getattr(self.ctx, 'conversation_id', None)
        
        self._checkpoint = await sync_to_async(
            StepCheckpoint.from_execution_state_dict
        )(
            data=state_dict,
            run_id=self.ctx.run_id,
            checkpoint_key=self.checkpoint_key,
            user=user,
            conversation_id=conversation_id,
        )

    async def _update_status(
        self,
        status: str,
        completed_at=None,
        last_error: Optional[str] = None,
    ) -> None:
        """Update the checkpoint status in the database."""
        if self._checkpoint is None:
            # Try to get existing checkpoint
            self._checkpoint = await sync_to_async(
                StepCheckpoint.objects.filter(
                    run_id=self.ctx.run_id,
                    checkpoint_key=self.checkpoint_key,
                ).first
            )()

        if self._checkpoint:
            self._checkpoint.status = status
            if completed_at:
                self._checkpoint.completed_at = completed_at
            if last_error:
                self._checkpoint.last_error = last_error

            update_fields = ["status", "updated_at"]
            if completed_at:
                update_fields.append("completed_at")
            if last_error:
                update_fields.append("last_error")

            await sync_to_async(self._checkpoint.save)(
                update_fields=update_fields
            )

    async def get_checkpoint(self) -> Optional[StepCheckpoint]:
        """
        Get the current checkpoint model instance.

        Returns:
            StepCheckpoint instance or None
        """
        if self._checkpoint:
            return self._checkpoint

        return await sync_to_async(
            StepCheckpoint.objects.filter(
                run_id=self.ctx.run_id,
                checkpoint_key=self.checkpoint_key,
            ).first
        )()

    @classmethod
    async def get_checkpoint_for_run(
        cls,
        run_id: UUID,
        checkpoint_key: str = "_step_executor_state",
    ) -> Optional[StepCheckpoint]:
        """
        Get checkpoint for a specific run.

        Args:
            run_id: The run ID to look up
            checkpoint_key: The checkpoint key

        Returns:
            StepCheckpoint instance or None
        """
        return await sync_to_async(
            StepCheckpoint.objects.filter(
                run_id=run_id,
                checkpoint_key=checkpoint_key,
            ).first
        )()

    @classmethod
    async def resume_from_checkpoint(
        cls,
        ctx,
        steps: list[Step],
        checkpoint_key: str = "_step_executor_state",
    ) -> dict[str, Any]:
        """
        Resume execution from an existing checkpoint.

        This is a convenience method for resuming a previously
        interrupted step sequence.

        Args:
            ctx: DjangoRunContext instance
            steps: List of steps to execute
            checkpoint_key: The checkpoint key to resume from

        Returns:
            Dictionary mapping step names to their results
        """
        executor = cls(ctx, checkpoint_key=checkpoint_key)
        return await executor.run(steps, resume=True)

