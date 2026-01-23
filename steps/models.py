"""
Django models for step execution state and events.

These models provide database-backed storage for:
- StepCheckpoint: Execution state for resumable step sequences
- StepEvent: Event log for step execution history
"""

import uuid
from django.conf import settings
from django.db import models


class StepStatusChoices(models.TextChoices):
    """Status choices for step execution."""
    
    PENDING = "pending", "Pending"
    RUNNING = "running", "Running"
    COMPLETED = "completed", "Completed"
    FAILED = "failed", "Failed"
    CANCELLED = "cancelled", "Cancelled"
    RETRYING = "retrying", "Retrying"


class StepCheckpoint(models.Model):
    """
    Stores execution state for resumable step sequences.
    
    This model enables step execution to be resumed after interruption
    by persisting the ExecutionState from agent-runtime-core.
    """
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    
    # Ownership and context
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="step_checkpoints",
        null=True,
        blank=True,
    )
    run_id = models.UUIDField(db_index=True)
    conversation_id = models.UUIDField(null=True, blank=True, db_index=True)
    
    # Checkpoint key for namespacing multiple executors
    checkpoint_key = models.CharField(max_length=255, default="_step_executor_state")
    
    # Execution state (serialized ExecutionState)
    execution_id = models.UUIDField(db_index=True)
    current_step_index = models.IntegerField(default=0)
    completed_steps = models.JSONField(default=list)
    step_results = models.JSONField(default=dict)
    custom_state = models.JSONField(default=dict)
    
    # Status tracking
    status = models.CharField(
        max_length=20,
        choices=StepStatusChoices.choices,
        default=StepStatusChoices.PENDING,
        db_index=True,
    )
    
    # Timing
    started_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    
    # Error tracking
    last_error = models.TextField(blank=True)
    total_attempts = models.IntegerField(default=0)
    
    # Metadata
    metadata = models.JSONField(default=dict, blank=True)
    
    class Meta:
        app_label = "django_agent_runtime"
        db_table = "agent_step_checkpoint"
        ordering = ["-updated_at"]
        unique_together = [("run_id", "checkpoint_key")]
        verbose_name = "Step Checkpoint"
        verbose_name_plural = "Step Checkpoints"
        indexes = [
            models.Index(fields=["user", "status"]),
            models.Index(fields=["run_id", "checkpoint_key"]),
        ]
    
    def __str__(self):
        return f"Checkpoint {self.execution_id} - Step {self.current_step_index} ({self.status})"
    
    def to_execution_state_dict(self) -> dict:
        """Convert to ExecutionState-compatible dictionary."""
        return {
            "execution_id": str(self.execution_id),
            "current_step_index": self.current_step_index,
            "completed_steps": self.completed_steps,
            "step_results": self.step_results,
            "started_at": self.started_at.isoformat(),
            "custom_state": self.custom_state,
        }
    
    @classmethod
    def from_execution_state_dict(
        cls,
        data: dict,
        run_id,
        checkpoint_key: str = "_step_executor_state",
        user=None,
        conversation_id=None,
    ):
        """Create or update from ExecutionState dictionary."""
        execution_id = uuid.UUID(data["execution_id"])
        
        checkpoint, created = cls.objects.update_or_create(
            run_id=run_id,
            checkpoint_key=checkpoint_key,
            defaults={
                "user": user,
                "conversation_id": conversation_id,
                "execution_id": execution_id,
                "current_step_index": data["current_step_index"],
                "completed_steps": data["completed_steps"],
                "step_results": data["step_results"],
                "custom_state": data.get("custom_state", {}),
                "status": StepStatusChoices.RUNNING,
            }
        )
        return checkpoint


class StepEventTypeChoices(models.TextChoices):
    """Event type choices matching agent-runtime-core EventType."""
    
    STEP_STARTED = "step_started", "Step Started"
    STEP_COMPLETED = "step_completed", "Step Completed"
    STEP_FAILED = "step_failed", "Step Failed"
    STEP_RETRYING = "step_retrying", "Step Retrying"
    STEP_SKIPPED = "step_skipped", "Step Skipped"
    PROGRESS_UPDATE = "progress_update", "Progress Update"


class StepEvent(models.Model):
    """
    Event log for step execution history.
    
    Records all events emitted during step execution for
    debugging, monitoring, and audit purposes.
    """
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    
    # Link to checkpoint
    checkpoint = models.ForeignKey(
        StepCheckpoint,
        on_delete=models.CASCADE,
        related_name="events",
        null=True,
        blank=True,
    )
    run_id = models.UUIDField(db_index=True)
    
    # Event details
    event_type = models.CharField(
        max_length=30,
        choices=StepEventTypeChoices.choices,
        db_index=True,
    )
    step_name = models.CharField(max_length=255, blank=True, db_index=True)
    step_index = models.IntegerField(null=True, blank=True)
    
    # Event payload
    payload = models.JSONField(default=dict)
    
    # Timing
    timestamp = models.DateTimeField(auto_now_add=True, db_index=True)
    
    class Meta:
        app_label = "django_agent_runtime"
        db_table = "agent_step_event"
        ordering = ["timestamp"]
        verbose_name = "Step Event"
        verbose_name_plural = "Step Events"
        indexes = [
            models.Index(fields=["run_id", "timestamp"]),
            models.Index(fields=["checkpoint", "timestamp"]),
        ]
    
    def __str__(self):
        return f"{self.event_type}: {self.step_name} at {self.timestamp}"

