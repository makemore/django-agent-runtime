"""
LangGraph adapter for django_agent_runtime.

This example shows how to integrate LangGraph agents with the runtime.
LangGraph provides a powerful graph-based approach to building agents
with state management, branching, and cycles.

Requirements:
    pip install langgraph langchain-openai

Usage:
    1. Add to RUNTIME_REGISTRY in settings:
       'RUNTIME_REGISTRY': ['django_agent_runtime.examples.langgraph_adapter:register']

    2. Create a run with agent_key="langgraph-agent"

Example LangGraph agent structure:
    - StateGraph with nodes for different agent steps
    - Conditional edges for routing
    - Checkpointing for state persistence
"""

from typing import Any, TypedDict, Annotated, Sequence
import operator

from django_agent_runtime.runtime.interfaces import (
    AgentRuntime,
    RunContext,
    RunResult,
    EventType,
)
from django_agent_runtime.runtime.registry import register_runtime


class AgentState(TypedDict):
    """State for the LangGraph agent."""
    messages: Annotated[Sequence[dict], operator.add]
    next_step: str
    iteration: int


class LangGraphRuntime(AgentRuntime):
    """
    Runtime adapter for LangGraph agents.

    This adapter:
    - Wraps a LangGraph StateGraph
    - Emits events for each node execution
    - Supports checkpointing via RunContext
    - Handles cancellation between steps
    """

    MAX_ITERATIONS = 20

    @property
    def key(self) -> str:
        return "langgraph-agent"

    async def run(self, ctx: RunContext) -> RunResult:
        """Execute the LangGraph agent."""
        try:
            from langgraph.graph import StateGraph, END
            from langchain_openai import ChatOpenAI
        except ImportError:
            raise ImportError(
                "LangGraph integration requires: pip install langgraph langchain-openai"
            )

        # Build the graph
        graph = self._build_graph()
        app = graph.compile()

        # Initialize state
        state: AgentState = {
            "messages": ctx.input_messages,
            "next_step": "agent",
            "iteration": 0,
        }

        # Run the graph
        total_usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}

        async for event in app.astream(state):
            # Check for cancellation
            if ctx.cancelled():
                await ctx.emit(EventType.RUN_CANCELLED, {"reason": "User requested"})
                return RunResult()

            # Emit step event
            for node_name, node_output in event.items():
                await ctx.emit(EventType.STEP_COMPLETED, {
                    "node": node_name,
                    "output": node_output,
                })

                # Checkpoint after each step
                await ctx.checkpoint({
                    "node": node_name,
                    "state": node_output,
                })

                # Update state
                if isinstance(node_output, dict):
                    state.update(node_output)

        # Extract final response
        final_messages = state.get("messages", [])
        final_output = {}

        if final_messages:
            last_message = final_messages[-1]
            if isinstance(last_message, dict):
                final_output = {"response": last_message.get("content", "")}
                await ctx.emit(EventType.ASSISTANT_MESSAGE, last_message)

        return RunResult(
            final_output=final_output,
            final_messages=final_messages,
            usage=total_usage,
        )

    def _build_graph(self):
        """Build the LangGraph StateGraph."""
        from langgraph.graph import StateGraph, END
        from langchain_openai import ChatOpenAI

        # Create the LLM
        llm = ChatOpenAI(model="gpt-4o", temperature=0)

        # Define nodes
        async def agent_node(state: AgentState) -> dict:
            """Main agent node - calls the LLM."""
            messages = state["messages"]
            response = await llm.ainvoke(messages)

            return {
                "messages": [{"role": "assistant", "content": response.content}],
                "next_step": "end",
                "iteration": state["iteration"] + 1,
            }

        async def should_continue(state: AgentState) -> str:
            """Determine if we should continue or end."""
            if state["iteration"] >= self.MAX_ITERATIONS:
                return "end"
            return state.get("next_step", "end")

        # Build graph
        graph = StateGraph(AgentState)
        graph.add_node("agent", agent_node)
        graph.set_entry_point("agent")
        graph.add_conditional_edges(
            "agent",
            should_continue,
            {"end": END, "agent": "agent"},
        )

        return graph


def register():
    """Register the LangGraph runtime."""
    register_runtime(LangGraphRuntime())

