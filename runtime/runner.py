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

from django.conf import settings as django_settings

from django_agent_runtime.conf import runtime_settings, get_event_visibility, should_swallow_exceptions
from django_agent_runtime.runtime.interfaces import (
    AgentRuntime,
    EventType,
    Message,
    RunContext,
    RunResult,
    ToolRegistry,
    ErrorInfo,
)
from django_agent_runtime.runtime.registry import get_runtime_async
from django_agent_runtime.runtime.queue.base import RunQueue, QueuedRun
from django_agent_runtime.runtime.events.base import EventBus, Event

logger = logging.getLogger(__name__)

# Check DEBUG mode
DEBUG = getattr(django_settings, 'DEBUG', False)


def debug_print(msg: str):
    """Print debug message if Django DEBUG is True."""
    if DEBUG:
        print(f"[agent-runner] {msg}", flush=True)


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
    metadata: dict
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

    # In-memory state dict for the current run (not persisted)
    state: dict = field(default_factory=dict, repr=False)

    async def emit(self, event_type: EventType | str, payload: dict) -> None:
        """Emit an event to the event bus."""
        event_type_str = event_type.value if isinstance(event_type, EventType) else event_type

        # Get visibility for this event type
        visibility_level, ui_visible = get_event_visibility(event_type_str)

        event = Event(
            run_id=self.run_id,
            seq=self._seq,
            event_type=event_type_str,
            payload=payload,
            timestamp=datetime.now(timezone.utc),
            visibility_level=visibility_level,
            ui_visible=ui_visible,
        )

        # Add detail for specific event types
        detail = ""
        if event_type == EventType.TOOL_CALL:
            tool_name = payload.get("name", "unknown")
            tool_args = str(payload.get("arguments", {}))[:80]
            detail = f" -> {tool_name}({tool_args})"
        elif event_type == EventType.ASSISTANT_MESSAGE:
            content = str(payload.get("content", ""))[:80]
            detail = f" -> {content}{'...' if len(str(payload.get('content', ''))) > 80 else ''}"

        # Include short run ID for easier debugging of concurrent runs
        short_id = str(self.run_id)[:8]
        debug_print(f"[{short_id}] Emitting event: type={event_type_str}, seq={self._seq}, visible={ui_visible}{detail}")
        await self._event_bus.publish(event)
        self._seq += 1

    async def emit_user_message(self, content: str) -> None:
        """
        Emit a message that will always be shown to the user.

        This is a convenience method for emitting assistant messages.

        Args:
            content: The message content to display
        """
        await self.emit(EventType.ASSISTANT_MESSAGE, {"content": content})

    async def emit_error(self, error: str, details: dict = None) -> None:
        """
        Emit an error that will be shown to the user.

        This is for runtime errors that should be displayed to users,
        distinct from run.failed which is the final failure event.

        Args:
            error: The error message
            details: Optional additional error details
        """
        await self.emit(EventType.ERROR, {
            "message": error,
            "details": details or {},
        })

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

        print(f"[agent-runner] Starting run {run_id} (agent={agent_key}, attempt={queued_run.attempt})", flush=True)

        # Start tracing
        if self.trace_sink:
            self.trace_sink.start_run(run_id, {"agent_key": agent_key})

        try:
            # Get the runtime
            debug_print(f"Getting runtime for agent_key={agent_key}")
            runtime = await get_runtime_async(agent_key)
            debug_print(f"Got runtime: {runtime.__class__.__name__}")

            # Build context
            ctx = await self._build_context(queued_run, runtime)
            debug_print(f"Context built: {len(ctx.input_messages)} messages")
            for i, msg in enumerate(ctx.input_messages):
                role = msg.get("role", "unknown")
                content = msg.get("content", "")[:100]  # Truncate for readability
                debug_print(f"  [{i}] {role}: {content}{'...' if len(msg.get('content', '')) > 100 else ''}")

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
                debug_print(f"Calling runtime.run() with timeout={self.settings.RUN_TIMEOUT_SECONDS}s")
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
                # In debug mode, re-raise exceptions immediately for full stack traces
                if not should_swallow_exceptions():
                    print(f"[agent-runner] Runtime error in run {run_id} (debug mode - re-raising): {e}", flush=True)
                    raise

                print(f"[agent-runner] Runtime error in run {run_id}: {e}", flush=True)
                traceback.print_exc()
                await self._handle_error(
                    run_id, ctx, runtime, e,
                    attempt=queued_run.attempt,
                    max_attempts=self.settings.DEFAULT_MAX_ATTEMPTS,
                )

            finally:
                heartbeat_task.cancel()
                try:
                    await heartbeat_task
                except asyncio.CancelledError:
                    pass

        except Exception as e:
            # In debug mode, re-raise exceptions immediately for full stack traces
            if not should_swallow_exceptions():
                print(f"[agent-runner] Failed to start run {run_id} (debug mode - re-raising): {e}", flush=True)
                raise

            # Error before run started (e.g., runtime not found)
            print(f"[agent-runner] Failed to start run {run_id}: {e}", flush=True)
            traceback.print_exc()
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
        new_messages = input_data.get("messages", [])
        params = input_data.get("params", {})

        # Get conversation_id from metadata
        conversation_id = queued_run.metadata.get("conversation_id")
        if conversation_id:
            conversation_id = UUID(conversation_id) if isinstance(conversation_id, str) else conversation_id

        # Load conversation history if enabled and we have a conversation
        messages = await self._load_conversation_history(
            conversation_id, new_messages, queued_run.run_id
        )

        # Build tool registry - load from database if agent_key is available
        tool_registry = ToolRegistry()
        agent_key = queued_run.agent_key
        if agent_key:
            try:
                from django_agent_runtime.dynamic_tools import load_agent_tools
                user_id = queued_run.metadata.get("user_id")
                tool_registry = await load_agent_tools(
                    agent_slug=agent_key,
                    agent_run_id=queued_run.run_id,
                    user_id=user_id,
                )
                logger.debug(f"Loaded {len(tool_registry.list_tools())} tools for agent {agent_key}")
            except Exception as e:
                logger.warning(f"Failed to load tools for agent {agent_key}: {e}")

        # Get next sequence number
        seq = await self.event_bus.get_next_seq(queued_run.run_id)

        return RunContextImpl(
            run_id=queued_run.run_id,
            conversation_id=conversation_id,
            input_messages=messages,
            params=params,
            metadata=queued_run.metadata,
            tool_registry=tool_registry,
            _event_bus=self.event_bus,
            _queue=self.queue,
            _worker_id=self.worker_id,
            _seq=seq,
        )

    async def _load_conversation_history(
        self,
        conversation_id: Optional[UUID],
        new_messages: list[Message],
        current_run_id: UUID,
    ) -> list[Message]:
        """
        Load conversation history and prepend to new messages.

        This enables multi-turn conversations by default. When a run is part of
        a conversation, previous messages from that conversation are automatically
        included in the context.

        Args:
            conversation_id: The conversation ID (if any)
            new_messages: The new messages for this run
            current_run_id: The current run ID (to exclude from history)

        Returns:
            Combined list of history + new messages
        """
        # Check if conversation history is enabled
        if not self.settings.INCLUDE_CONVERSATION_HISTORY:
            debug_print("Conversation history disabled by settings")
            return new_messages

        if not conversation_id:
            debug_print("No conversation_id, skipping history load")
            return new_messages

        try:
            # Import here to avoid circular imports
            from django_agent_runtime.models import AgentConversation
            from asgiref.sync import sync_to_async

            # Get the conversation
            try:
                conversation = await sync_to_async(
                    AgentConversation.objects.get
                )(id=conversation_id)
            except AgentConversation.DoesNotExist:
                debug_print(f"Conversation {conversation_id} not found")
                return new_messages

            # Get message history from previous runs (excluding current run)
            # This uses the model's get_message_history method which handles
            # deduplication and proper ordering
            history = await sync_to_async(
                lambda: conversation.get_message_history(include_failed_runs=False)
            )()

            if not history:
                debug_print("No conversation history found")
                return new_messages

            # Apply message limit if configured
            max_messages = self.settings.MAX_HISTORY_MESSAGES
            if max_messages and len(history) > max_messages:
                debug_print(f"Limiting history from {len(history)} to {max_messages} messages")
                history = history[-max_messages:]

            debug_print(f"Loaded {len(history)} history messages for conversation {conversation_id}")

            # Combine history with new messages
            # History comes first, then new messages
            return history + new_messages

        except Exception as e:
            logger.warning(f"Failed to load conversation history: {e}")
            debug_print(f"Error loading history: {e}")
            # Fall back to just new messages on error
            return new_messages

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
                print(f"[agent-runner] Lost lease on run {run_id}", flush=True)
                break

            # Emit heartbeat event
            await ctx.emit(EventType.RUN_HEARTBEAT, {})

            # Check for cancellation
            await ctx.check_cancelled()

    async def _handle_success(
        self, run_id: UUID, ctx: RunContextImpl, result: RunResult
    ) -> None:
        """Handle successful run completion."""
        print(f"[agent-runner] Run {run_id} succeeded", flush=True)

        output = {
            "final_output": result.final_output,
            "final_messages": result.final_messages,
            "usage": result.usage,
            "artifacts": result.artifacts,
        }

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
            output=output,
        )

        # Generate conversation title if this is the first run
        if ctx.conversation_id and self.settings.AUTO_GENERATE_CONVERSATION_TITLE:
            await self._maybe_generate_conversation_title(
                ctx.conversation_id,
                ctx.input_messages,
                result.final_messages,
            )

        # Call completion hook if configured
        await self._call_completion_hook(run_id, output)

    async def _call_completion_hook(self, run_id: UUID, output: dict) -> None:
        """Call the configured completion hook if any."""
        from django_agent_runtime.conf import get_hook

        hook = get_hook(self.settings.RUN_COMPLETED_HOOK)
        if not hook:
            return

        try:
            # Run hook in thread pool since it may do sync I/O
            from asgiref.sync import sync_to_async
            await sync_to_async(hook)(str(run_id), output)
        except Exception as e:
            # In debug mode, re-raise exceptions immediately
            if not should_swallow_exceptions():
                print(f"[agent-runner] Error in completion hook for run {run_id} (debug mode - re-raising): {e}", flush=True)
                raise
            print(f"[agent-runner] Error in completion hook for run {run_id}: {e}", flush=True)

    async def _maybe_generate_conversation_title(
        self,
        conversation_id: UUID,
        input_messages: list[Message],
        final_messages: list[Message],
    ) -> None:
        """
        Generate a title for the conversation if it doesn't have one.

        Only generates a title for the first successful run in a conversation.
        Uses a fast/cheap model to generate a short, descriptive title.
        """
        from asgiref.sync import sync_to_async
        from django_agent_runtime.models import AgentConversation

        try:
            # Check if conversation already has a title
            conversation = await sync_to_async(
                AgentConversation.objects.get
            )(id=conversation_id)

            if conversation.title:
                # Already has a title, skip
                debug_print(f"Conversation {conversation_id} already has title: {conversation.title}")
                return

            # Check if this is the first run (no other successful runs)
            run_count = await sync_to_async(
                lambda: conversation.runs.filter(status="succeeded").count()
            )()

            if run_count > 1:
                # Not the first run, skip
                debug_print(f"Conversation {conversation_id} has {run_count} runs, skipping title generation")
                return

            # Extract user message and assistant response for title generation
            user_message = None
            assistant_message = None

            for msg in input_messages:
                if msg.get("role") == "user":
                    user_message = msg.get("content", "")
                    break

            for msg in final_messages:
                if msg.get("role") == "assistant":
                    content = msg.get("content", "")
                    if content:
                        assistant_message = content
                        break

            if not user_message:
                debug_print("No user message found, skipping title generation")
                return

            # Generate title using LLM
            title = await self._generate_title(user_message, assistant_message)

            if title:
                # Update conversation title
                await sync_to_async(
                    lambda: AgentConversation.objects.filter(id=conversation_id).update(title=title)
                )()
                debug_print(f"Generated title for conversation {conversation_id}: {title}")

        except AgentConversation.DoesNotExist:
            debug_print(f"Conversation {conversation_id} not found for title generation")
        except Exception as e:
            # Don't fail the run if title generation fails
            print(f"[agent-runner] Error generating conversation title: {e}", flush=True)

    async def _generate_title(
        self,
        user_message: str,
        assistant_message: Optional[str] = None,
    ) -> Optional[str]:
        """
        Generate a short title for a conversation using LLM.

        Args:
            user_message: The first user message
            assistant_message: The first assistant response (optional)

        Returns:
            A short title (max ~50 chars) or None if generation fails
        """
        from django_agent_runtime.runtime.llm import get_llm_client

        try:
            # Build prompt for title generation
            context = f"User: {user_message[:500]}"  # Limit to avoid huge prompts
            if assistant_message:
                context += f"\n\nAssistant: {assistant_message[:500]}"

            messages = [
                {
                    "role": "system",
                    "content": (
                        "Generate a very short, descriptive title (3-6 words, max 50 characters) "
                        "for this conversation. The title should capture the main topic or intent. "
                        "Respond with ONLY the title, no quotes, no punctuation at the end."
                    ),
                },
                {
                    "role": "user",
                    "content": context,
                },
            ]

            # Use a fast/cheap model for title generation (OpenAI gpt-4o-mini by default)
            llm = get_llm_client(provider="openai")
            response = await llm.generate(
                messages=messages,
                model=self.settings.TITLE_GENERATION_MODEL,
                max_tokens=50,
                temperature=0.7,
            )

            title = response.message.get("content", "").strip()

            # Clean up the title
            title = title.strip('"\'')  # Remove quotes if present
            title = title.rstrip('.')   # Remove trailing period

            # Truncate if too long
            if len(title) > 100:
                title = title[:97] + "..."

            return title if title else None

        except Exception as e:
            print(f"[agent-runner] Error calling LLM for title generation: {e}", flush=True)
            return None

    async def _handle_timeout(self, run_id: UUID, ctx: RunContextImpl) -> None:
        """Handle run timeout."""
        print(f"[agent-runner] Run {run_id} timed out after {self.settings.RUN_TIMEOUT_SECONDS}s", flush=True)

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
        print(f"[agent-runner] Run {run_id} cancelled", flush=True)

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
        attempt: int = 1,
        max_attempts: int = None,
    ) -> None:
        """Handle run error with retry logic."""
        if max_attempts is None:
            max_attempts = self.settings.DEFAULT_MAX_ATTEMPTS

        print(f"[agent-runner] Run {run_id} failed (attempt {attempt}/{max_attempts}): {error}", flush=True)

        # Let runtime classify the error
        error_info = await runtime.on_error(ctx, error)
        if error_info is None:
            error_info = ErrorInfo(
                type=type(error).__name__,
                message=str(error),
                stack=traceback.format_exc(),
                retriable=True,
            )

        # Build comprehensive error dict for events and storage
        error_dict = {
            "type": error_info.type,
            "message": error_info.message,
            "stack": error_info.stack,
            "retriable": error_info.retriable,
            "details": error_info.details,
        }

        # Check if we should retry
        can_retry = error_info.retriable and attempt < max_attempts

        if can_retry:
            # Try to requeue
            requeued = await self.queue.requeue_for_retry(
                run_id,
                self.worker_id,
                error_dict,
                delay_seconds=self._calculate_backoff(ctx, attempt),
            )

            if requeued:
                print(f"[agent-runner] Run {run_id} requeued for retry (attempt {attempt + 1})", flush=True)
                # Emit an error event so UI knows about the retry
                await ctx.emit(EventType.ERROR, {
                    "message": f"Error occurred, retrying... (attempt {attempt}/{max_attempts})",
                    "error": error_info.message,
                    "error_type": error_info.type,
                    "attempt": attempt,
                    "max_attempts": max_attempts,
                    "retriable": True,
                })
                return

        # Final failure - emit detailed run.failed event
        await ctx.emit(EventType.RUN_FAILED, {
            "error": error_dict["message"],
            "error_type": error_dict["type"],
            "error_details": error_dict,
            "attempt": attempt,
            "max_attempts": max_attempts,
            "retriable": False,  # No more retries
        })

        await self.queue.release(
            run_id,
            self.worker_id,
            success=False,
            error=error_dict,
        )

    def _calculate_backoff(self, ctx: RunContextImpl, attempt: int = 1) -> int:
        """Calculate exponential backoff delay."""
        base = self.settings.RETRY_BACKOFF_BASE
        max_backoff = self.settings.RETRY_BACKOFF_MAX

        delay = min(base ** attempt, max_backoff)
        return int(delay)
