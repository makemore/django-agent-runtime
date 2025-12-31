"""
Tests for django_agent_runtime registry.
"""

import pytest
from unittest.mock import patch, MagicMock

from django_agent_runtime.runtime.registry import (
    register_runtime,
    get_runtime,
    list_runtimes,
    clear_registry,
    unregister_runtime,
)
from django_agent_runtime.runtime.interfaces import AgentRuntime, RunContext, RunResult


@pytest.fixture(autouse=True)
def clear_registry_fixture():
    """Clear the runtime registry before and after each test."""
    clear_registry()
    yield
    clear_registry()


class TestRuntimeRegistry:
    """Tests for runtime registry functions."""

    def test_register_runtime(self, mock_runtime):
        """Test registering a runtime."""
        register_runtime(mock_runtime)

        assert "mock-agent" in list_runtimes()
        assert get_runtime("mock-agent") is mock_runtime

    def test_register_multiple_runtimes(self):
        """Test registering multiple runtimes."""
        from django_agent_runtime.tests.conftest import MockAgentRuntime

        runtime1 = MockAgentRuntime(key="agent-1")
        runtime2 = MockAgentRuntime(key="agent-2")

        register_runtime(runtime1)
        register_runtime(runtime2)

        keys = list_runtimes()
        assert len(keys) == 2
        assert "agent-1" in keys
        assert "agent-2" in keys

    def test_register_duplicate_key_overwrites(self, mock_runtime):
        """Test that registering with duplicate key overwrites."""
        from django_agent_runtime.tests.conftest import MockAgentRuntime

        runtime1 = MockAgentRuntime(key="same-key")
        runtime2 = MockAgentRuntime(key="same-key")

        register_runtime(runtime1)
        register_runtime(runtime2)

        assert get_runtime("same-key") is runtime2

    def test_get_runtime(self, mock_runtime):
        """Test getting a registered runtime."""
        register_runtime(mock_runtime)

        retrieved = get_runtime("mock-agent")

        assert retrieved is mock_runtime

    def test_get_runtime_not_found(self):
        """Test getting a non-existent runtime raises KeyError."""
        with pytest.raises(KeyError):
            get_runtime("nonexistent")

    def test_list_runtimes(self):
        """Test listing all registered runtimes."""
        from django_agent_runtime.tests.conftest import MockAgentRuntime

        runtime1 = MockAgentRuntime(key="agent-1")
        runtime2 = MockAgentRuntime(key="agent-2")

        register_runtime(runtime1)
        register_runtime(runtime2)

        keys = list_runtimes()

        assert len(keys) == 2
        assert "agent-1" in keys
        assert "agent-2" in keys

    def test_list_runtimes_empty(self):
        """Test listing runtimes when none registered."""
        keys = list_runtimes()

        assert keys == []


class TestRuntimeDiscovery:
    """Tests for runtime discovery from settings."""

    def test_autodiscover_runtimes_exists(self):
        """Test autodiscover_runtimes function exists."""
        from django_agent_runtime.runtime.registry import autodiscover_runtimes

        # Just verify the function exists and is callable
        assert callable(autodiscover_runtimes)


def _test_register():
    """Test registration function for discovery tests."""
    from django_agent_runtime.tests.conftest import MockAgentRuntime
    register_runtime(MockAgentRuntime(key="discovered-agent"))


class TestCustomRuntime:
    """Tests for creating custom runtimes."""
    
    def test_custom_runtime_implementation(self):
        """Test implementing a custom runtime."""
        
        class CustomRuntime(AgentRuntime):
            @property
            def key(self) -> str:
                return "custom-agent"
            
            async def run(self, ctx: RunContext) -> RunResult:
                return RunResult(
                    final_output={"custom": True},
                    final_messages=[],
                )
        
        runtime = CustomRuntime()
        register_runtime(runtime)
        
        assert get_runtime("custom-agent") is runtime
    
    @pytest.mark.asyncio
    async def test_custom_runtime_execution(self):
        """Test executing a custom runtime."""
        from uuid import uuid4
        from unittest.mock import MagicMock

        class EchoRuntime(AgentRuntime):
            @property
            def key(self) -> str:
                return "echo-agent"

            async def run(self, ctx) -> RunResult:
                # Echo back the last user message
                last_message = ctx.input_messages[-1]["content"]
                return RunResult(
                    final_output={"echo": last_message},
                    final_messages=[{"role": "assistant", "content": last_message}],
                )

        runtime = EchoRuntime()

        # Create a mock context (RunContext is a Protocol, can't be instantiated)
        ctx = MagicMock()
        ctx.input_messages = [{"role": "user", "content": "Hello, World!"}]

        result = await runtime.run(ctx)

        assert result.final_output["echo"] == "Hello, World!"
        assert result.final_messages[0]["content"] == "Hello, World!"

