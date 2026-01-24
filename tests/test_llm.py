"""
Tests for django_agent_runtime LLM client implementations.
"""

import pytest
from unittest.mock import patch, AsyncMock, MagicMock

from django_agent_runtime.runtime.llm import get_llm_client, OpenAIClient
from django_agent_runtime.runtime.interfaces import LLMResponse


class TestOpenAIClient:
    """Tests for OpenAIClient."""

    @pytest.fixture
    def mock_openai(self):
        """Create a mock OpenAI client."""
        # Now OpenAIClient is imported from agent_runtime_core
        with patch("agent_runtime_core.llm.openai.AsyncOpenAI") as mock:
            mock_instance = MagicMock()
            mock.return_value = mock_instance
            
            # Mock the chat completions
            mock_response = MagicMock()
            mock_response.choices = [
                MagicMock(
                    message=MagicMock(
                        role="assistant",
                        content="Hello! How can I help you?",
                        tool_calls=None,
                    )
                )
            ]
            mock_response.usage = MagicMock(
                prompt_tokens=10,
                completion_tokens=8,
                total_tokens=18,
            )
            
            mock_instance.chat.completions.create = AsyncMock(return_value=mock_response)
            
            yield mock_instance
    
    @pytest.mark.asyncio
    async def test_generate_simple_message(self, mock_openai):
        """Test generating a simple message."""
        client = OpenAIClient(api_key="test-key")
        
        messages = [{"role": "user", "content": "Hello"}]
        response = await client.generate(messages)
        
        assert isinstance(response, LLMResponse)
        assert response.message["role"] == "assistant"
        assert "Hello" in response.message["content"]
        assert response.usage["total_tokens"] == 18
    
    @pytest.mark.asyncio
    async def test_generate_with_model(self, mock_openai):
        """Test generating with specific model."""
        client = OpenAIClient(api_key="test-key", default_model="gpt-4")

        messages = [{"role": "user", "content": "Hello"}]
        await client.generate(messages)

        # Verify model was passed
        call_kwargs = mock_openai.chat.completions.create.call_args.kwargs
        assert call_kwargs["model"] == "gpt-4"
    
    @pytest.mark.asyncio
    async def test_generate_with_tools(self, mock_openai):
        """Test generating with tools."""
        client = OpenAIClient(api_key="test-key")
        
        messages = [{"role": "user", "content": "What is 2+2?"}]
        tools = [
            {
                "type": "function",
                "function": {
                    "name": "calculate",
                    "description": "Calculate math",
                    "parameters": {"type": "object", "properties": {}},
                },
            }
        ]
        
        await client.generate(messages, tools=tools)
        
        call_kwargs = mock_openai.chat.completions.create.call_args.kwargs
        assert "tools" in call_kwargs
    
    @pytest.mark.asyncio
    async def test_generate_with_tool_calls_response(self, mock_openai):
        """Test handling tool calls in response."""
        # Setup mock to return tool calls
        mock_tool_call = MagicMock()
        mock_tool_call.id = "call_123"
        mock_tool_call.type = "function"
        mock_tool_call.function.name = "calculate"
        mock_tool_call.function.arguments = '{"expression": "2+2"}'
        
        mock_response = MagicMock()
        mock_response.choices = [
            MagicMock(
                message=MagicMock(
                    role="assistant",
                    content=None,
                    tool_calls=[mock_tool_call],
                )
            )
        ]
        mock_response.usage = MagicMock(
            prompt_tokens=10,
            completion_tokens=5,
            total_tokens=15,
        )
        
        mock_openai.chat.completions.create = AsyncMock(return_value=mock_response)
        
        client = OpenAIClient(api_key="test-key")
        response = await client.generate([{"role": "user", "content": "Calculate 2+2"}])
        
        assert "tool_calls" in response.message
        assert len(response.message["tool_calls"]) == 1
        assert response.message["tool_calls"][0]["function"]["name"] == "calculate"


# Check if openai package is available
try:
    import openai
    HAS_OPENAI = True
except ImportError:
    HAS_OPENAI = False


@pytest.mark.skipif(not HAS_OPENAI, reason="OpenAI package not installed")
class TestGetLLMClient:
    """Tests for get_llm_client factory function."""

    @patch("django_agent_runtime.conf.runtime_settings")
    def test_get_openai_client(self, mock_settings):
        """Test getting OpenAI client."""
        mock_settings.return_value = MagicMock(
            MODEL_PROVIDER="openai",
            DEFAULT_MODEL="gpt-4o",
            LITELLM_ENABLED=False,
        )

        with patch.dict("os.environ", {"OPENAI_API_KEY": "test-key"}):
            client = get_llm_client()

        assert isinstance(client, OpenAIClient)

    @patch("django_agent_runtime.conf.runtime_settings")
    def test_get_client_with_custom_model(self, mock_settings):
        """Test getting client with custom model."""
        mock_settings.return_value = MagicMock(
            MODEL_PROVIDER="openai",
            DEFAULT_MODEL="gpt-4o",
            LITELLM_ENABLED=False,
        )

        with patch.dict("os.environ", {"OPENAI_API_KEY": "test-key"}):
            client = get_llm_client(default_model="gpt-4-turbo")

        assert client.default_model == "gpt-4-turbo"


class TestMockLLMClient:
    """Tests for MockLLMClient fixture."""
    
    @pytest.mark.asyncio
    async def test_mock_client_generates_response(self, mock_llm_client):
        """Test that mock client generates responses."""
        messages = [{"role": "user", "content": "Hello"}]
        response = await mock_llm_client.generate(messages)
        
        assert response.message["role"] == "assistant"
        assert response.message["content"] == "Mock LLM response"
    
    @pytest.mark.asyncio
    async def test_mock_client_tracks_calls(self, mock_llm_client):
        """Test that mock client tracks calls."""
        messages = [{"role": "user", "content": "Hello"}]
        
        await mock_llm_client.generate(messages)
        await mock_llm_client.generate(messages)
        
        assert mock_llm_client.call_count == 2
        assert mock_llm_client.last_messages == messages

