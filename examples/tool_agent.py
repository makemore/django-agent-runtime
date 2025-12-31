"""
Tool-using agent example.

This demonstrates an agent that:
- Has access to tools
- Calls tools when the LLM requests them
- Handles the tool call loop

Usage:
    1. Add to RUNTIME_REGISTRY in settings:
       'RUNTIME_REGISTRY': ['django_agent_runtime.examples.tool_agent:register']

    2. Create a run with agent_key="tool-agent"
"""

import json
from django_agent_runtime.runtime.interfaces import (
    AgentRuntime,
    RunContext,
    RunResult,
    EventType,
    ToolDefinition,
)
from django_agent_runtime.runtime.registry import register_runtime
from django_agent_runtime.runtime.llm import get_llm_client


class ToolAgentRuntime(AgentRuntime):
    """
    An agent that can use tools.

    Demonstrates the tool calling loop pattern.
    """

    MAX_ITERATIONS = 10

    @property
    def key(self) -> str:
        return "tool-agent"

    async def run(self, ctx: RunContext) -> RunResult:
        """Execute the tool agent."""
        llm = get_llm_client()
        messages = list(ctx.input_messages)
        total_usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}

        # Register example tools
        self._register_tools(ctx.tool_registry)

        for iteration in range(self.MAX_ITERATIONS):
            # Check for cancellation
            if ctx.cancelled():
                break

            # Checkpoint state
            await ctx.checkpoint({
                "iteration": iteration,
                "messages": messages,
            })

            # Call LLM with tools
            response = await llm.generate(
                messages=messages,
                tools=ctx.tool_registry.to_openai_format(),
                **ctx.params,
            )

            # Accumulate usage
            for key in total_usage:
                total_usage[key] += response.usage.get(key, 0)

            assistant_message = response.message
            messages.append(assistant_message)

            # Check for tool calls
            tool_calls = assistant_message.get("tool_calls", [])

            if not tool_calls:
                # No tool calls - we're done
                await ctx.emit(EventType.ASSISTANT_MESSAGE, {
                    "content": assistant_message.get("content", ""),
                    "role": "assistant",
                })
                break

            # Execute tool calls
            for tool_call in tool_calls:
                func = tool_call.get("function", {})
                tool_name = func.get("name", "")
                tool_args = json.loads(func.get("arguments", "{}"))

                # Emit tool call event
                await ctx.emit(EventType.TOOL_CALL, {
                    "id": tool_call.get("id"),
                    "name": tool_name,
                    "arguments": tool_args,
                })

                # Execute tool
                try:
                    result = await ctx.tool_registry.execute(tool_name, tool_args)
                    result_str = json.dumps(result) if not isinstance(result, str) else result
                except Exception as e:
                    result_str = f"Error: {e}"

                # Emit tool result event
                await ctx.emit(EventType.TOOL_RESULT, {
                    "id": tool_call.get("id"),
                    "name": tool_name,
                    "result": result_str,
                })

                # Add tool result to messages
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.get("id"),
                    "content": result_str,
                })

        return RunResult(
            final_output={"response": messages[-1].get("content", "")},
            final_messages=messages,
            usage=total_usage,
        )

    def _register_tools(self, registry):
        """Register example tools."""
        # Example: Calculator tool
        async def calculate(expression: str) -> str:
            """Evaluate a math expression."""
            try:
                result = eval(expression, {"__builtins__": {}}, {})
                return str(result)
            except Exception as e:
                return f"Error: {e}"

        registry.register(ToolDefinition(
            name="calculate",
            description="Evaluate a mathematical expression",
            parameters={
                "type": "object",
                "properties": {
                    "expression": {
                        "type": "string",
                        "description": "The math expression to evaluate",
                    },
                },
                "required": ["expression"],
            },
            handler=calculate,
        ))


def register():
    """Register the tool agent runtime."""
    register_runtime(ToolAgentRuntime())

