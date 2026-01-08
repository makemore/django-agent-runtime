"""
Tests for django_agent_runtime interfaces.
"""

import pytest
from uuid import uuid4

from django_agent_runtime.runtime.interfaces import (
    RunContext,
    RunResult,
    ToolRegistry,
    ToolDefinition,
    EventType,
)
from django_agent_runtime.runtime.runner import RunContextImpl


class TestRunContext:
    """Tests for RunContext (via RunContextImpl)."""

    @pytest.mark.asyncio
    async def test_run_context_creation(self):
        """Test creating a RunContextImpl."""
        from unittest.mock import AsyncMock

        mock_event_bus = AsyncMock()
        mock_queue = AsyncMock()

        ctx = RunContextImpl(
            run_id=uuid4(),
            conversation_id=None,
            input_messages=[{"role": "user", "content": "Hello"}],
            params={"temperature": 0.7},
            metadata={},
            tool_registry=ToolRegistry(),
            _event_bus=mock_event_bus,
            _queue=mock_queue,
            _worker_id="test-worker",
        )

        assert len(ctx.input_messages) == 1
        assert ctx.params["temperature"] == 0.7

    @pytest.mark.asyncio
    async def test_run_context_cancellation(self):
        """Test cancellation checking."""
        from unittest.mock import AsyncMock

        mock_event_bus = AsyncMock()
        mock_queue = AsyncMock()
        mock_queue.is_cancelled = AsyncMock(return_value=False)

        ctx = RunContextImpl(
            run_id=uuid4(),
            conversation_id=None,
            input_messages=[],
            params={},
            metadata={},
            tool_registry=ToolRegistry(),
            _event_bus=mock_event_bus,
            _queue=mock_queue,
            _worker_id="test-worker",
        )

        assert not ctx.cancelled()

        ctx._is_cancelled = True
        assert ctx.cancelled()

    @pytest.mark.asyncio
    async def test_run_context_tool_registry(self):
        """Test tool registry access."""
        from unittest.mock import AsyncMock

        mock_event_bus = AsyncMock()
        mock_queue = AsyncMock()

        ctx = RunContextImpl(
            run_id=uuid4(),
            conversation_id=None,
            input_messages=[],
            params={},
            metadata={},
            tool_registry=ToolRegistry(),
            _event_bus=mock_event_bus,
            _queue=mock_queue,
            _worker_id="test-worker",
        )

        assert ctx.tool_registry is not None
        assert isinstance(ctx.tool_registry, ToolRegistry)


class TestRunResult:
    """Tests for RunResult."""

    def test_run_result_defaults(self):
        """Test RunResult default values."""
        result = RunResult()

        assert result.final_output == {}
        assert result.final_messages == []
        assert result.usage == {}
    
    def test_run_result_with_data(self):
        """Test RunResult with data."""
        result = RunResult(
            final_output={"response": "Hello!"},
            final_messages=[{"role": "assistant", "content": "Hello!"}],
            usage={"prompt_tokens": 10, "completion_tokens": 5},
        )
        
        assert result.final_output["response"] == "Hello!"
        assert len(result.final_messages) == 1
        assert result.usage["prompt_tokens"] == 10


class TestToolRegistry:
    """Tests for ToolRegistry."""
    
    def test_register_tool(self, tool_registry):
        """Test registering a tool."""
        assert "add_numbers" in tool_registry._tools
        assert "greet" in tool_registry._tools
    
    def test_get_tool(self, tool_registry):
        """Test getting a tool."""
        tool = tool_registry.get("add_numbers")
        
        assert tool is not None
        assert tool.name == "add_numbers"
    
    def test_get_nonexistent_tool(self, tool_registry):
        """Test getting a nonexistent tool."""
        tool = tool_registry.get("nonexistent")
        
        assert tool is None
    
    @pytest.mark.asyncio
    async def test_execute_tool(self, tool_registry):
        """Test executing a tool."""
        result = await tool_registry.execute("add_numbers", {"a": 2, "b": 3})
        
        assert result == 5
    
    @pytest.mark.asyncio
    async def test_execute_tool_with_string_result(self, tool_registry):
        """Test executing a tool that returns a string."""
        result = await tool_registry.execute("greet", {"name": "World"})
        
        assert result == "Hello, World!"
    
    @pytest.mark.asyncio
    async def test_execute_nonexistent_tool(self, tool_registry):
        """Test executing a nonexistent tool raises error."""
        with pytest.raises(KeyError):
            await tool_registry.execute("nonexistent", {})
    
    def test_to_openai_format(self, tool_registry):
        """Test converting tools to OpenAI format."""
        tools = tool_registry.to_openai_format()
        
        assert len(tools) == 2
        
        add_tool = next(t for t in tools if t["function"]["name"] == "add_numbers")
        assert add_tool["type"] == "function"
        assert "description" in add_tool["function"]
        assert "parameters" in add_tool["function"]
    
    def test_list_tools(self, tool_registry):
        """Test listing all tools."""
        tools = tool_registry.list_tools()

        assert len(tools) == 2
        names = [t.name for t in tools]
        assert "add_numbers" in names
        assert "greet" in names


class TestToolDefinition:
    """Tests for ToolDefinition."""
    
    def test_tool_definition_creation(self):
        """Test creating a ToolDefinition."""
        async def handler(x: int) -> int:
            return x * 2
        
        tool = ToolDefinition(
            name="double",
            description="Double a number",
            parameters={
                "type": "object",
                "properties": {"x": {"type": "integer"}},
                "required": ["x"],
            },
            handler=handler,
        )
        
        assert tool.name == "double"
        assert tool.description == "Double a number"
        assert tool.handler is handler


class TestEventType:
    """Tests for EventType enum."""
    
    def test_event_types_exist(self):
        """Test that expected event types exist."""
        assert EventType.RUN_STARTED == "run.started"
        assert EventType.RUN_SUCCEEDED == "run.succeeded"
        assert EventType.RUN_FAILED == "run.failed"
        assert EventType.TOOL_CALL == "tool.call"
        assert EventType.TOOL_RESULT == "tool.result"
        assert EventType.ASSISTANT_MESSAGE == "assistant.message"

