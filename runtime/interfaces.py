"""
Core interfaces for the Django Agent Runtime.

These interfaces are the stable public API. Everything else can change.
Agent frameworks (LangGraph, CrewAI, custom) adapt to these interfaces.

SEMVER PROTECTED - Breaking changes require major version bump.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Optional, Protocol, TypedDict
from uuid import UUID


class EventVisibility(str, Enum):
    """
    Visibility levels for events.

    Controls which events are shown to users in the UI.
    """

    INTERNAL = "internal"  # Never shown to UI (checkpoints, heartbeats)
    DEBUG = "debug"  # Shown only in debug mode (tool calls, tool results)
    USER = "user"  # Always shown to users (assistant messages, errors)


class EventType(str, Enum):
    """
    Standard event types emitted by agent runtimes.

    All agent frameworks must emit through these types.
    """

    # Lifecycle events
    RUN_STARTED = "run.started"
    RUN_HEARTBEAT = "run.heartbeat"
    RUN_SUCCEEDED = "run.succeeded"
    RUN_FAILED = "run.failed"
    RUN_CANCELLED = "run.cancelled"
    RUN_TIMED_OUT = "run.timed_out"

    # Message events
    ASSISTANT_DELTA = "assistant.delta"  # Token streaming (optional)
    ASSISTANT_MESSAGE = "assistant.message"  # Complete message

    # Tool events
    TOOL_CALL = "tool.call"
    TOOL_RESULT = "tool.result"

    # State events
    STATE_CHECKPOINT = "state.checkpoint"

    # Error events (distinct from run.failed - for runtime errors shown to users)
    ERROR = "error"


class Message(TypedDict, total=False):
    """
    Framework-neutral message format.

    Compatible with OpenAI, Anthropic, and other providers.
    """

    role: str  # "system" | "user" | "assistant" | "tool"
    content: str | dict | list  # String or structured content
    name: Optional[str]  # For tool messages
    tool_call_id: Optional[str]  # For tool results
    tool_calls: Optional[list]  # For assistant tool calls
    metadata: dict  # Additional metadata


@dataclass
class RunResult:
    """
    Result returned by an agent runtime after execution.

    This is what the runner receives when an agent completes.
    """

    final_output: dict = field(default_factory=dict)
    final_messages: list[Message] = field(default_factory=list)
    usage: dict = field(default_factory=dict)  # Token usage, costs, etc.
    artifacts: dict = field(default_factory=dict)  # Files, images, etc.


@dataclass
class ErrorInfo:
    """Structured error information for failed runs."""

    type: str  # Error class name
    message: str
    stack: str = ""
    retriable: bool = True
    details: dict = field(default_factory=dict)


class RunContext(Protocol):
    """
    Context provided to agent runtimes during execution.

    This is what agent frameworks use to interact with the runtime.
    Implementations are provided by the runner.
    """

    @property
    def run_id(self) -> UUID:
        """Unique identifier for this run."""
        ...

    @property
    def conversation_id(self) -> Optional[UUID]:
        """Conversation this run belongs to (if any)."""
        ...

    @property
    def input_messages(self) -> list[Message]:
        """Input messages for this run."""
        ...

    @property
    def params(self) -> dict:
        """Additional parameters for this run."""
        ...

    @property
    def metadata(self) -> dict:
        """Metadata associated with this run (e.g., channel_id, user context)."""
        ...

    @property
    def tool_registry(self) -> "ToolRegistry":
        """Registry of available tools for this agent."""
        ...

    async def emit(self, event_type: EventType | str, payload: dict) -> None:
        """
        Emit an event to the event bus.

        Args:
            event_type: Type of event (use EventType enum)
            payload: Event payload data
        """
        ...

    async def emit_user_message(self, content: str) -> None:
        """
        Emit a message that will always be shown to the user.

        This is a convenience method for emitting assistant messages.

        Args:
            content: The message content to display
        """
        ...

    async def emit_error(self, error: str, details: dict = None) -> None:
        """
        Emit an error that will be shown to the user.

        This is for runtime errors that should be displayed to users,
        distinct from run.failed which is the final failure event.

        Args:
            error: The error message
            details: Optional additional error details
        """
        ...

    async def checkpoint(self, state: dict) -> None:
        """
        Save a state checkpoint for recovery.

        Args:
            state: Serializable state to checkpoint
        """
        ...

    async def get_state(self) -> Optional[dict]:
        """
        Get the last checkpointed state.

        Returns:
            The last saved state, or None if no checkpoint exists.
        """
        ...

    def cancelled(self) -> bool:
        """
        Check if cancellation has been requested.

        Agent runtimes should check this between steps.
        """
        ...


class AgentRuntime(ABC):
    """
    Base class for agent runtime implementations.

    Subclass this to create custom agent runtimes.
    Each runtime is identified by a unique key.
    """

    @property
    @abstractmethod
    def key(self) -> str:
        """
        Unique identifier for this runtime.

        Used to route runs to the correct runtime.
        """
        ...

    @abstractmethod
    async def run(self, ctx: RunContext) -> RunResult:
        """
        Execute an agent run.

        Args:
            ctx: Runtime context with input, tools, and event emission

        Returns:
            RunResult with final output and messages

        Raises:
            Exception: On unrecoverable errors (will be caught by runner)
        """
        ...

    async def cancel(self, ctx: RunContext) -> None:
        """
        Handle cancellation request.

        Override for custom cleanup. Default does nothing.
        Called when cancellation is requested but run is still active.
        """
        pass

    async def on_error(self, ctx: RunContext, error: Exception) -> Optional[ErrorInfo]:
        """
        Handle an error during execution.

        Override to customize error handling/classification.
        Return ErrorInfo to control retry behavior.
        """
        return ErrorInfo(
            type=type(error).__name__,
            message=str(error),
            retriable=True,
        )


@dataclass
class ToolDefinition:
    """Definition of a tool available to agents."""

    name: str
    description: str
    parameters: dict  # JSON Schema for parameters
    handler: Callable  # async def handler(**kwargs) -> Any
    has_side_effects: bool = False
    requires_confirmation: bool = False
    metadata: dict = field(default_factory=dict)


class ToolRegistry:
    """
    Registry of tools available to a specific agent.

    Tools are allow-listed per agent_key for security.
    """

    def __init__(self):
        self._tools: dict[str, ToolDefinition] = {}

    def register(self, tool: ToolDefinition) -> None:
        """Register a tool."""
        self._tools[tool.name] = tool

    def get(self, name: str) -> Optional[ToolDefinition]:
        """Get a tool by name."""
        return self._tools.get(name)

    def list_tools(self) -> list[ToolDefinition]:
        """List all registered tools."""
        return list(self._tools.values())

    def to_openai_format(self) -> list[dict]:
        """Convert tools to OpenAI function calling format."""
        return [
            {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.parameters,
                },
            }
            for tool in self._tools.values()
        ]

    def get_tool_definitions(self) -> list[dict]:
        """Alias for to_openai_format() for backwards compatibility."""
        return self.to_openai_format()

    async def execute(self, name: str, arguments: dict) -> Any:
        """
        Execute a tool by name.

        Args:
            name: Tool name
            arguments: Tool arguments

        Returns:
            Tool result

        Raises:
            KeyError: If tool not found
        """
        tool = self._tools.get(name)
        if not tool:
            raise KeyError(f"Tool not found: {name}")
        return await tool.handler(**arguments)


class LLMClient(ABC):
    """
    Abstract LLM client interface.

    Implementations: OpenAIClient, AnthropicClient, LiteLLMClient, etc.
    This abstraction is what makes the runtime model-agnostic.
    """

    @abstractmethod
    async def generate(
        self,
        messages: list[Message],
        *,
        model: Optional[str] = None,
        stream: bool = False,
        tools: Optional[list[dict]] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        **kwargs,
    ) -> "LLMResponse":
        """
        Generate a completion from the LLM.

        Args:
            messages: Conversation messages
            model: Model identifier (uses default if not specified)
            stream: Whether to stream the response
            tools: Tool definitions in OpenAI format
            temperature: Sampling temperature
            max_tokens: Maximum tokens to generate
            **kwargs: Provider-specific parameters

        Returns:
            LLMResponse with message and usage info
        """
        ...

    @abstractmethod
    async def stream(
        self,
        messages: list[Message],
        *,
        model: Optional[str] = None,
        tools: Optional[list[dict]] = None,
        **kwargs,
    ):
        """
        Stream a completion from the LLM.

        Yields:
            LLMStreamChunk objects with deltas
        """
        ...


@dataclass
class LLMResponse:
    """Response from an LLM generation."""

    message: Message
    usage: dict = field(default_factory=dict)  # prompt_tokens, completion_tokens, etc.
    model: str = ""
    finish_reason: str = ""
    raw_response: Optional[Any] = None

    @property
    def tool_calls(self) -> Optional[list]:
        """Extract tool_calls from the message for convenience."""
        if isinstance(self.message, dict):
            calls = self.message.get("tool_calls")
            if calls:
                # Convert to objects with name, arguments, id attributes
                return [ToolCall(tc) for tc in calls]
        return None

    @property
    def content(self) -> str:
        """Extract content from the message for convenience."""
        if isinstance(self.message, dict):
            return self.message.get("content", "")
        return ""


class ToolCall:
    """Wrapper for tool call data to provide attribute access."""
    
    def __init__(self, data: dict):
        self._data = data
    
    @property
    def id(self) -> str:
        return self._data.get("id", "")
    
    @property
    def name(self) -> str:
        func = self._data.get("function", {})
        return func.get("name", "")
    
    @property
    def arguments(self) -> dict:
        func = self._data.get("function", {})
        args = func.get("arguments", "{}")
        if isinstance(args, str):
            import json
            try:
                return json.loads(args)
            except json.JSONDecodeError:
                return {}
        return args


@dataclass
class LLMStreamChunk:
    """A chunk from a streaming LLM response."""

    delta: str = ""
    tool_calls: Optional[list] = None
    finish_reason: Optional[str] = None
    usage: Optional[dict] = None


class TraceSink(ABC):
    """
    Abstract trace sink for observability.

    Implementations: NoopTraceSink, LangfuseTraceSink, OpenTelemetrySink, etc.
    """

    @abstractmethod
    def start_run(self, run_id: UUID, metadata: dict) -> None:
        """Start tracing a run."""
        ...

    @abstractmethod
    def log_event(self, run_id: UUID, event_type: str, payload: dict) -> None:
        """Log an event within a run."""
        ...

    @abstractmethod
    def end_run(self, run_id: UUID, outcome: str, metadata: Optional[dict] = None) -> None:
        """End tracing a run."""
        ...

    def flush(self) -> None:
        """Flush any buffered traces. Default is no-op."""
        pass

