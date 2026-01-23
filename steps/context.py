"""
Django implementation of RunContext for step execution.

Provides a RunContext that uses:
- Django's cache framework for events (optional)
- Django's database for checkpoints
- Integration with Django's user model
"""

import asyncio
from datetime import datetime
from typing import Any, Optional
from uuid import UUID, uuid4

from django.core.cache import cache
from asgiref.sync import sync_to_async

from agent_runtime_core.interfaces import EventType, Message, ToolRegistry


class DjangoRunContext:
    """
    Django implementation of the RunContext protocol.
    
    This context uses Django's ORM for checkpoint persistence and
    optionally Django's cache framework for event storage.
    
    Example:
        ctx = DjangoRunContext(
            run_id=uuid4(),
            user=request.user,
            input_messages=[Message(role="user", content="Hello")],
        )
        
        # Use with StepExecutor
        executor = DjangoStepExecutor(ctx)
        results = await executor.run(steps)
    """
    
    def __init__(
        self,
        run_id: UUID,
        *,
        user=None,
        conversation_id: Optional[UUID] = None,
        input_messages: Optional[list[Message]] = None,
        params: Optional[dict] = None,
        metadata: Optional[dict] = None,
        tool_registry: Optional[ToolRegistry] = None,
        use_cache_for_events: bool = True,
        event_cache_timeout: int = 3600,  # 1 hour
    ):
        """
        Initialize the Django run context.
        
        Args:
            run_id: Unique identifier for this run
            user: Django user instance (optional)
            conversation_id: Associated conversation ID (optional)
            input_messages: Input messages for this run
            params: Additional parameters
            metadata: Run metadata
            tool_registry: Registry of available tools
            use_cache_for_events: Whether to cache events (default: True)
            event_cache_timeout: Cache timeout for events in seconds
        """
        self._run_id = run_id
        self._user = user
        self._conversation_id = conversation_id
        self._input_messages = input_messages or []
        self._params = params or {}
        self._metadata = metadata or {}
        self._tool_registry = tool_registry or ToolRegistry()
        self._cancelled = False
        self._use_cache_for_events = use_cache_for_events
        self._event_cache_timeout = event_cache_timeout
        self._state: Optional[dict] = None
    
    @property
    def run_id(self) -> UUID:
        """Unique identifier for this run."""
        return self._run_id
    
    @property
    def conversation_id(self) -> Optional[UUID]:
        """Conversation this run belongs to (if any)."""
        return self._conversation_id
    
    @property
    def input_messages(self) -> list[Message]:
        """Input messages for this run."""
        return self._input_messages
    
    @property
    def params(self) -> dict:
        """Additional parameters for this run."""
        return self._params
    
    @property
    def metadata(self) -> dict:
        """Metadata associated with this run."""
        return self._metadata
    
    @property
    def tool_registry(self) -> ToolRegistry:
        """Registry of available tools for this agent."""
        return self._tool_registry
    
    @property
    def user(self):
        """Django user associated with this run."""
        return self._user
    
    async def emit(self, event_type: EventType | str, payload: dict) -> None:
        """
        Emit an event.
        
        Events are stored in the database via StepEvent model and
        optionally cached for quick access.
        """
        from django_agent_runtime.steps.models import StepEvent, StepCheckpoint
        
        # Convert EventType enum to string if needed
        if hasattr(event_type, 'value'):
            event_type_str = event_type.value
        else:
            event_type_str = str(event_type)
        
        # Get checkpoint if exists
        checkpoint = None
        try:
            checkpoint = await sync_to_async(
                StepCheckpoint.objects.filter(run_id=self._run_id).first
            )()
        except Exception:
            pass
        
        # Create event record
        event = await sync_to_async(StepEvent.objects.create)(
            checkpoint=checkpoint,
            run_id=self._run_id,
            event_type=event_type_str,
            step_name=payload.get("step_name", ""),
            step_index=payload.get("step_index"),
            payload=payload,
        )
        
        # Cache event for quick access
        if self._use_cache_for_events:
            cache_key = f"step_events:{self._run_id}"
            events = cache.get(cache_key, [])
            events.append({
                "id": str(event.id),
                "event_type": event_type_str,
                "step_name": payload.get("step_name", ""),
                "payload": payload,
                "timestamp": datetime.utcnow().isoformat(),
            })
            cache.set(cache_key, events, self._event_cache_timeout)
    
    async def checkpoint(self, state: dict) -> None:
        """
        Save a state checkpoint for recovery.

        Uses Django's ORM to persist the checkpoint.
        """
        from django_agent_runtime.steps.models import StepCheckpoint

        self._state = state

        # Save to database
        await sync_to_async(StepCheckpoint.from_execution_state_dict)(
            data=state,
            run_id=self._run_id,
            user=self._user,
            conversation_id=self._conversation_id,
        )

    async def get_state(self) -> Optional[dict]:
        """
        Get the last checkpointed state.

        Returns:
            The last saved state, or None if no checkpoint exists.
        """
        from django_agent_runtime.steps.models import StepCheckpoint

        if self._state is not None:
            return self._state

        try:
            checkpoint = await sync_to_async(
                StepCheckpoint.objects.filter(run_id=self._run_id).first
            )()
            if checkpoint:
                self._state = checkpoint.to_execution_state_dict()
                return self._state
        except Exception:
            pass

        return None

    def cancelled(self) -> bool:
        """Check if cancellation has been requested."""
        return self._cancelled

    def cancel(self) -> None:
        """Request cancellation of this run."""
        self._cancelled = True

    def get_cached_events(self) -> list[dict]:
        """
        Get cached events for this run.

        Returns:
            List of cached event dictionaries
        """
        if not self._use_cache_for_events:
            return []
        cache_key = f"step_events:{self._run_id}"
        return cache.get(cache_key, [])

    async def get_events(self) -> list:
        """
        Get all events for this run from the database.

        Returns:
            List of StepEvent instances
        """
        from django_agent_runtime.steps.models import StepEvent

        events = await sync_to_async(list)(
            StepEvent.objects.filter(run_id=self._run_id).order_by("timestamp")
        )
        return events

