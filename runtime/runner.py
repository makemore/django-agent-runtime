"""
Core runner for executing agent runs.

Handles:
- Claiming runs from queue
- Executing agent runtimes
- Heartbeats and lease management
- Retries and error handling
- Cancellation
- Event emission
"""

import asyncio
import logging
import traceback
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from django_agent_runtime.conf import runtime_settings
from django_agent_runtime.runtime.interfaces import (
    AgentRuntime,
    EventType,
    Message,
    RunContext,
    RunResult,
    ToolRegistry,
    ErrorInfo,
)
from django_agent_runtime.runtime.registry import get_runtime
from django_agent_runtime.runtime.queue.base import RunQueue, QueuedRun
from django_agent_runtime.runtime.events.base import EventBus, Event

logger = logging.getLogger(__name__)


@dataclass
class RunContextImpl:
    """
    Concrete implementation of RunContext.

    Provided to agent runtimes during execution.
    """

    run_id: UUID
    conversation_id: Optional[UUID]
    input_messages: list[Message]
    params: dict
    tool_registry: ToolRegistry

    # Internal state
    _event_bus: EventBus = field(repr=False)
    _queue: RunQueue = field(repr=False)
    _worker_id: str = field(repr=False)
    _seq: int = field(default=0, repr=False)
    _state: Optional[dict] = field(default=None, repr=False)
    _cancel_check_interval: float = field(default=1.0, repr=False)
    _last_cancel_check: float = field(default=0.0, repr=False)
    _is_cancelled: bool = field(default=False, repr=False)

    async def emit(self, event_type: EventType | str, payload: dict) -> None:
        """Emit an event to the event bus."""
        event_type_str = event_type.value if isinstance(event_type, EventType) else event_type

        event = Event(
            run_id=self.run_id,
            seq=self._seq,
            event_type=event_type_str,
            payload=payload,
            timestamp=datetime.now(timezone.utc),
        )

        await self._event_bus.publish(event)
        self._seq += 1

    async def checkpoint(self, state: dict) -> None:
        """Save a state checkpoint."""
        from asgiref.sync import sync_to_async
        from django_agent_runtime.models import AgentCheckpoint

        self._state = state

        @sync_to_async
        def _save():
            # Get next checkpoint seq
            last = AgentCheckpoint.objects.filter(run_id=self.run_id).order_by("-seq").first()
            next_seq = (last.seq + 1) if last else 0

            AgentCheckpoint.objects.create(
                run_id=self.run_id,
                seq=next_seq,
                state=state,
            )

        await _save()

        # Also emit checkpoint event
        await self.emit(EventType.STATE_CHECKPOINT, {"seq": self._seq - 1})

    async def get_state(self) -> Optional[dict]:
        """Get the last checkpointed state."""
        if self._state is not None:
            return self._state

        from asgiref.sync import sync_to_async
        from django_agent_runtime.models import AgentCheckpoint

        @sync_to_async
        def _get():
            checkpoint = (
                AgentCheckpoint.objects.filter(run_id=self.run_id)
                .order_by("-seq")
                .first()
            )
            return checkpoint.state if checkpoint else None

        self._state = await _get()
        return self._state

    def cancelled(self) -> bool:
        """Check if cancellation has been requested."""
        return self._is_cancelled

    async def check_cancelled(self) -> bool:
        """
        Async check for cancellation (queries database).

        Call this periodically in long-running operations.
        """
        now = asyncio.get_event_loop().time()
        if now - self._last_cancel_check < self._cancel_check_interval:
            return self._is_cancelled

        self._last_cancel_check = now
        self._is_cancelled = await self._queue.is_cancelled(self.run_id)
        return self._is_cancelled


class AgentRunner:
    """
    Main runner for executing agent runs.

    Manages the lifecycle of runs including:
    - Claiming from queue
    - Executing with timeout
    - Heartbeat management
    - Error handling and retries
    - Cancellation
    """

    def __init__(
        self,
        worker_id: str,
        queue: RunQueue,
        event_bus: EventBus,
        trace_sink: Optional["TraceSink"] = None,
    ):
        self.worker_id = worker_id
        self.queue = queue
        self.event_bus = event_bus
        self.trace_sink = trace_sink
        self.settings = runtime_settings()

        self._running = False
        self._current_runs: dict[UUID, asyncio.Task] = {}

    async def run_once(self, queued_run: QueuedRun) -> None:
        """Execute a single run."""
        run_id = queued_run.run_id
        agent_key = queued_run.agent_key

        logger.info(f"Starting run {run_id} (agent={agent_key}, attempt={queued_run.attempt})")

        # Start tracing
        if self.trace_sink:
            self.trace_sink.start_run(run_id, {"agent_key": agent_key})

        try:
            # Get the runtime
            runtime = get_runtime(agent_key)

            # Build context
            ctx = await self._build_context(queued_run, runtime)

            # Emit started event
            await ctx.emit(EventType.RUN_STARTED, {
                "agent_key": agent_key,
                "attempt": queued_run.attempt,
            })

            # Start heartbeat task
            heartbeat_task = asyncio.create_task(
                self._heartbeat_loop(run_id, ctx)
            )

            try:
                # Execute with timeout
                result = await asyncio.wait_for(
                    runtime.run(ctx),
                    timeout=self.settings.RUN_TIMEOUT_SECONDS,
                )

                # Check for cancellation
                if ctx.cancelled():
                    await self._handle_cancellation(run_id, ctx)
                    return

                # Success!
                await self._handle_success(run_id, ctx, result)

            except asyncio.TimeoutError:
                await self._handle_timeout(run_id, ctx)

            except asyncio.CancelledError:
                await self._handle_cancellation(run_id, ctx)

            except Exception as e:
                await self._handle_error(run_id, ctx, runtime, e)

            finally:
                heartbeat_task.cancel()
                try:
                    await heartbeat_task
                except asyncio.CancelledError:
                    pass

        except Exception as e:
            # Error before run started (e.g., runtime not found)
            logger.exception(f"Failed to start run {run_id}: {e}")
            await self.queue.release(
                run_id,
                self.worker_id,
                success=False,
                error={
                    "type": type(e).__name__,
                    "message": str(e),
                    "stack": traceback.format_exc(),
                    "retriable": False,
                },
            )

        finally:
            if self.trace_sink:
                self.trace_sink.end_run(run_id, "completed")

    async def _build_context(
        self, queued_run: QueuedRun, runtime: AgentRuntime
    ) -> RunContextImpl:
        """Build the run context."""
        input_data = queued_run.input
        messages = input_data.get("messages", [])
        params = input_data.get("params", {})

        # Get conversation_id from metadata
        conversation_id = queued_run.metadata.get("conversation_id")
        if conversation_id:
            conversation_id = UUID(conversation_id) if isinstance(conversation_id, str) else conversation_id

        # Build tool registry (could be customized per agent)
        tool_registry = ToolRegistry()

        # Get next sequence number
        seq = await self.event_bus.get_next_seq(queued_run.run_id)

        return RunContextImpl(
            run_id=queued_run.run_id,
            conversation_id=conversation_id,
            input_messages=messages,
            params=params,
            tool_registry=tool_registry,
            _event_bus=self.event_bus,
            _queue=self.queue,
            _worker_id=self.worker_id,
            _seq=seq,
        )

    async def _heartbeat_loop(self, run_id: UUID, ctx: RunContextImpl) -> None:
        """Send periodic heartbeats to extend lease."""
        while True:
            await asyncio.sleep(self.settings.HEARTBEAT_INTERVAL_SECONDS)

            # Extend lease
            extended = await self.queue.extend_lease(
                run_id,
                self.worker_id,
                self.settings.LEASE_TTL_SECONDS,
            )

            if not extended:
                logger.warning(f"Lost lease on run {run_id}")
                break

            # Emit heartbeat event
            await ctx.emit(EventType.RUN_HEARTBEAT, {})

            # Check for cancellation
            await ctx.check_cancelled()

    async def _handle_success(
        self, run_id: UUID, ctx: RunContextImpl, result: RunResult
    ) -> None:
        """Handle successful run completion."""
        logger.info(f"Run {run_id} succeeded")

        # Emit success event
        await ctx.emit(EventType.RUN_SUCCEEDED, {
            "output": result.final_output,
            "usage": result.usage,
        })

        # Release with success
        await self.queue.release(
            run_id,
            self.worker_id,
            success=True,
            output={
                "final_output": result.final_output,
                "final_messages": result.final_messages,
                "usage": result.usage,
                "artifacts": result.artifacts,
            },
        )

    async def _handle_timeout(self, run_id: UUID, ctx: RunContextImpl) -> None:
        """Handle run timeout."""
        logger.warning(f"Run {run_id} timed out")

        await ctx.emit(EventType.RUN_TIMED_OUT, {
            "timeout_seconds": self.settings.RUN_TIMEOUT_SECONDS,
        })

        await self.queue.release(
            run_id,
            self.worker_id,
            success=False,
            error={
                "type": "TimeoutError",
                "message": f"Run exceeded {self.settings.RUN_TIMEOUT_SECONDS}s timeout",
                "retriable": False,
            },
        )

    async def _handle_cancellation(self, run_id: UUID, ctx: RunContextImpl) -> None:
        """Handle run cancellation."""
        logger.info(f"Run {run_id} cancelled")

        await ctx.emit(EventType.RUN_CANCELLED, {})

        # Update status directly (not through queue.release)
        from asgiref.sync import sync_to_async
        from django_agent_runtime.models import AgentRun
        from django_agent_runtime.models.base import RunStatus

        @sync_to_async
        def _update():
            AgentRun.objects.filter(id=run_id).update(
                status=RunStatus.CANCELLED,
                finished_at=datetime.now(timezone.utc),
                lease_owner="",
                lease_expires_at=None,
            )

        await _update()

    async def _handle_error(
        self,
        run_id: UUID,
        ctx: RunContextImpl,
        runtime: AgentRuntime,
        error: Exception,
    ) -> None:
        """Handle run error with retry logic."""
        logger.exception(f"Run {run_id} failed: {error}")

        # Let runtime classify the error
        error_info = await runtime.on_error(ctx, error)
        if error_info is None:
            error_info = ErrorInfo(
                type=type(error).__name__,
                message=str(error),
                stack=traceback.format_exc(),
                retriable=True,
            )

        error_dict = {
            "type": error_info.type,
            "message": error_info.message,
            "stack": error_info.stack,
            "retriable": error_info.retriable,
            "details": error_info.details,
        }

        if error_info.retriable:
            # Try to requeue
            requeued = await self.queue.requeue_for_retry(
                run_id,
                self.worker_id,
                error_dict,
                delay_seconds=self._calculate_backoff(ctx),
            )

            if requeued:
                logger.info(f"Run {run_id} requeued for retry")
                return

        # Final failure
        await ctx.emit(EventType.RUN_FAILED, {"error": error_dict})

        await self.queue.release(
            run_id,
            self.worker_id,
            success=False,
            error=error_dict,
        )

    def _calculate_backoff(self, ctx: RunContextImpl) -> int:
        """Calculate exponential backoff delay."""
        from django_agent_runtime.models import AgentRun
        from asgiref.sync import async_to_sync

        # This is called from async context, but we need sync access
        # In practice, attempt is already in the context
        attempt = 1  # Default

        base = self.settings.RETRY_BACKOFF_BASE
        max_backoff = self.settings.RETRY_BACKOFF_MAX

        delay = min(base ** attempt, max_backoff)
        return int(delay)
