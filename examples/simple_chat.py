"""
Simple chat agent example.

This demonstrates a basic agent that:
- Takes user messages
- Calls an LLM
- Returns the response

Usage:
    1. Add to RUNTIME_REGISTRY in settings:
       'RUNTIME_REGISTRY': ['django_agent_runtime.examples.simple_chat:register']

    2. Create a run with agent_key="simple-chat"
"""

from django_agent_runtime.runtime.interfaces import (
    AgentRuntime,
    RunContext,
    RunResult,
    EventType,
)
from django_agent_runtime.runtime.registry import register_runtime
from django_agent_runtime.runtime.llm import get_llm_client


class SimpleChatRuntime(AgentRuntime):
    """
    A simple chat agent that forwards messages to an LLM.

    This is the most basic agent - no tools, no state, just chat.
    """

    @property
    def key(self) -> str:
        return "simple-chat"

    async def run(self, ctx: RunContext) -> RunResult:
        """Execute the chat agent."""
        # Get LLM client
        llm = get_llm_client()

        # Check for cancellation
        if ctx.cancelled():
            return RunResult()

        # Call LLM
        response = await llm.generate(
            messages=ctx.input_messages,
            **ctx.params,
        )

        # Emit the assistant message
        await ctx.emit(EventType.ASSISTANT_MESSAGE, {
            "content": response.message.get("content", ""),
            "role": "assistant",
        })

        # Return result
        return RunResult(
            final_output={"response": response.message.get("content", "")},
            final_messages=[response.message],
            usage=response.usage,
        )


def register():
    """Register the simple chat runtime."""
    register_runtime(SimpleChatRuntime())

