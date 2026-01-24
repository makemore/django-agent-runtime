"""
Django Agent Runtime interfaces.

This module re-exports all interfaces from agent_runtime_core for backwards
compatibility. New code should import directly from agent_runtime_core.

SEMVER PROTECTED - Breaking changes require major version bump.
"""

# Re-export everything from agent_runtime_core
from agent_runtime_core.interfaces import (
    # Enums
    EventType,
    EventVisibility,
    # TypedDicts
    Message,
    # Dataclasses
    RunResult,
    ErrorInfo,
    LLMResponse,
    LLMStreamChunk,
    LLMToolCall,
    # Classes
    Tool,
    ToolDefinition,
    ToolRegistry,
    LLMClient,
    TraceSink,
    # Protocols
    RunContext,
    # ABCs
    AgentRuntime,
)

# Backwards compatibility alias - Django code used ToolCall for LLMToolCall
ToolCall = LLMToolCall

__all__ = [
    # Enums
    "EventType",
    "EventVisibility",
    # TypedDicts
    "Message",
    # Dataclasses
    "RunResult",
    "ErrorInfo",
    "LLMResponse",
    "LLMStreamChunk",
    "LLMToolCall",
    # Classes
    "Tool",
    "ToolDefinition",
    "ToolRegistry",
    "LLMClient",
    "TraceSink",
    # Protocols
    "RunContext",
    # ABCs
    "AgentRuntime",
    # Backwards compatibility
    "ToolCall",
]

