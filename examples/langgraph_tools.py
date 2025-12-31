"""
LangGraph agent with tools example.

This demonstrates a more complete LangGraph agent that:
- Uses tools for external actions
- Has a ReAct-style reasoning loop
- Emits detailed events for UI streaming

Requirements:
    pip install langgraph langchain-openai langchain-core

Usage:
    1. Add to RUNTIME_REGISTRY in settings:
       'RUNTIME_REGISTRY': ['django_agent_runtime.examples.langgraph_tools:register']

    2. Create a run with agent_key="langgraph-tools-agent"
"""

from typing import Any, TypedDict, Annotated, Sequence, Literal
import operator
import json

from django_agent_runtime.runtime.interfaces import (
    AgentRuntime,
    RunContext,
    RunResult,
    EventType,
)
from django_agent_runtime.runtime.registry import register_runtime


class ToolsAgentState(TypedDict):
    """State for the tools agent."""
    messages: Annotated[Sequence[dict], operator.add]
    tool_calls: list[dict]
    iteration: int


class LangGraphToolsRuntime(AgentRuntime):
    """
    LangGraph agent with tool calling capabilities.

    Implements a ReAct-style loop:
    1. Agent decides what to do
    2. If tool call needed, execute tool
    3. Feed result back to agent
    4. Repeat until done
    """

    MAX_ITERATIONS = 10

    @property
    def key(self) -> str:
        return "langgraph-tools-agent"

    async def run(self, ctx: RunContext) -> RunResult:
        """Execute the tools agent."""
        try:
            from langgraph.graph import StateGraph, END
            from langchain_openai import ChatOpenAI
            from langchain_core.messages import HumanMessage, AIMessage, ToolMessage
        except ImportError:
            raise ImportError(
                "LangGraph tools integration requires: "
                "pip install langgraph langchain-openai langchain-core"
            )

        # Define tools
        tools = self._get_tools()

        # Create LLM with tools
        llm = ChatOpenAI(model="gpt-4o", temperature=0).bind_tools(tools)

        # Build and compile graph
        graph = self._build_graph(llm, tools, ctx)
        app = graph.compile()

        # Initialize state
        state: ToolsAgentState = {
            "messages": ctx.input_messages,
            "tool_calls": [],
            "iteration": 0,
        }

        # Run the graph
        final_state = None
        async for event in app.astream(state):
            if ctx.cancelled():
                return RunResult()

            for node_name, node_output in event.items():
                final_state = node_output
                await ctx.checkpoint({"node": node_name, "iteration": state["iteration"]})

        # Extract result
        messages = final_state.get("messages", []) if final_state else []
        final_content = ""
        if messages:
            last = messages[-1]
            final_content = last.get("content", "") if isinstance(last, dict) else str(last)

        await ctx.emit(EventType.ASSISTANT_MESSAGE, {
            "role": "assistant",
            "content": final_content,
        })

        return RunResult(
            final_output={"response": final_content},
            final_messages=messages,
        )

    def _get_tools(self) -> list:
        """Define available tools."""
        from langchain_core.tools import tool

        @tool
        def search(query: str) -> str:
            """Search for information."""
            # Mock search - replace with real implementation
            return f"Search results for: {query}"

        @tool
        def calculate(expression: str) -> str:
            """Evaluate a math expression."""
            try:
                result = eval(expression, {"__builtins__": {}}, {})
                return str(result)
            except Exception as e:
                return f"Error: {e}"

        return [search, calculate]

    def _build_graph(self, llm, tools, ctx: RunContext):
        """Build the ReAct-style graph."""
        from langgraph.graph import StateGraph, END
        from langchain_core.messages import ToolMessage

        tool_map = {t.name: t for t in tools}

        async def agent_node(state: ToolsAgentState) -> dict:
            """Call the LLM."""
            response = await llm.ainvoke(state["messages"])
            tool_calls = getattr(response, "tool_calls", [])

            return {
                "messages": [response],
                "tool_calls": tool_calls,
                "iteration": state["iteration"] + 1,
            }

        async def tool_node(state: ToolsAgentState) -> dict:
            """Execute tool calls."""
            results = []
            for tc in state["tool_calls"]:
                tool = tool_map.get(tc["name"])
                if tool:
                    result = await tool.ainvoke(tc["args"])
                    results.append(ToolMessage(content=str(result), tool_call_id=tc["id"]))
            return {"messages": results, "tool_calls": []}

        def should_continue(state: ToolsAgentState) -> Literal["tools", "end"]:
            if state["iteration"] >= self.MAX_ITERATIONS:
                return "end"
            return "tools" if state["tool_calls"] else "end"

        graph = StateGraph(ToolsAgentState)
        graph.add_node("agent", agent_node)
        graph.add_node("tools", tool_node)
        graph.set_entry_point("agent")
        graph.add_conditional_edges("agent", should_continue, {"tools": "tools", "end": END})
        graph.add_edge("tools", "agent")

        return graph


def register():
    """Register the LangGraph tools runtime."""
    register_runtime(LangGraphToolsRuntime())

