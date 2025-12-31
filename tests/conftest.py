"""
Pytest fixtures for django_agent_runtime tests.
"""

import pytest
from uuid import uuid4
from unittest.mock import AsyncMock, MagicMock

from django.contrib.auth import get_user_model

from django_agent_runtime.models import AgentRun, AgentConversation, AgentEvent
from django_agent_runtime.models.base import RunStatus
from django_agent_runtime.runtime.interfaces import (
    AgentRuntime,
    RunContext,
    RunResult,
    LLMClient,
    LLMResponse,
    ToolRegistry,
)


User = get_user_model()


@pytest.fixture
def user(db):
    """Create a test user."""
    return User.objects.create_user(
        email="test@example.com",
        password="testpass123",
    )


@pytest.fixture
def conversation(db, user):
    """Create a test conversation."""
    return AgentConversation.objects.create(
        user=user,
        agent_key="test-agent",
        title="Test Conversation",
    )


@pytest.fixture
def agent_run(db, conversation):
    """Create a test agent run."""
    return AgentRun.objects.create(
        conversation=conversation,
        agent_key="test-agent",
        input={"messages": [{"role": "user", "content": "Hello"}]},
        max_attempts=3,
    )


@pytest.fixture
def completed_run(db, conversation):
    """Create a completed agent run."""
    from django.utils import timezone
    
    run = AgentRun.objects.create(
        conversation=conversation,
        agent_key="test-agent",
        input={"messages": [{"role": "user", "content": "Hello"}]},
        status=RunStatus.SUCCEEDED,
        output={"response": "Hi there!"},
        started_at=timezone.now(),
        finished_at=timezone.now(),
    )
    return run


class MockAgentRuntime(AgentRuntime):
    """Mock agent runtime for testing."""
    
    def __init__(self, key: str = "mock-agent", should_fail: bool = False):
        self._key = key
        self.should_fail = should_fail
        self.run_count = 0
    
    @property
    def key(self) -> str:
        return self._key
    
    async def run(self, ctx: RunContext) -> RunResult:
        self.run_count += 1
        
        if self.should_fail:
            raise ValueError("Mock failure")
        
        return RunResult(
            final_output={"response": "Mock response"},
            final_messages=[{"role": "assistant", "content": "Mock response"}],
            usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        )


@pytest.fixture
def mock_runtime():
    """Create a mock agent runtime."""
    return MockAgentRuntime()


@pytest.fixture
def failing_runtime():
    """Create a failing agent runtime."""
    return MockAgentRuntime(should_fail=True)


class MockLLMClient(LLMClient):
    """Mock LLM client for testing."""

    def __init__(self, response_content: str = "Mock LLM response"):
        self.response_content = response_content
        self.call_count = 0
        self.last_messages = None

    async def generate(self, messages, **kwargs) -> LLMResponse:
        self.call_count += 1
        self.last_messages = messages

        return LLMResponse(
            message={"role": "assistant", "content": self.response_content},
            usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
            raw_response={"mock": True},
        )

    async def stream(self, messages, **kwargs):
        """Mock streaming - yields a single chunk."""
        self.call_count += 1
        self.last_messages = messages
        yield {"role": "assistant", "content": self.response_content}

    async def close(self):
        pass


@pytest.fixture
def mock_llm_client():
    """Create a mock LLM client."""
    return MockLLMClient()


@pytest.fixture
def tool_registry():
    """Create a tool registry with test tools."""
    registry = ToolRegistry()
    
    async def add_numbers(a: int, b: int) -> int:
        return a + b
    
    async def greet(name: str) -> str:
        return f"Hello, {name}!"
    
    from django_agent_runtime.runtime.interfaces import ToolDefinition
    
    registry.register(ToolDefinition(
        name="add_numbers",
        description="Add two numbers together",
        parameters={
            "type": "object",
            "properties": {
                "a": {"type": "integer"},
                "b": {"type": "integer"},
            },
            "required": ["a", "b"],
        },
        handler=add_numbers,
    ))
    
    registry.register(ToolDefinition(
        name="greet",
        description="Greet someone by name",
        parameters={
            "type": "object",
            "properties": {
                "name": {"type": "string"},
            },
            "required": ["name"],
        },
        handler=greet,
    ))
    
    return registry

