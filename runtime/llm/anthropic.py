"""
Anthropic API client implementation.
"""

import os
from typing import AsyncIterator, Optional

from django_agent_runtime.runtime.interfaces import (
    LLMClient,
    LLMResponse,
    LLMStreamChunk,
    Message,
)

try:
    from anthropic import AsyncAnthropic, APIError
except ImportError:
    AsyncAnthropic = None
    APIError = None


class AnthropicConfigurationError(Exception):
    """Raised when Anthropic API key is not configured."""
    pass


class AnthropicClient(LLMClient):
    """
    Anthropic API client.

    Supports Claude models.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        default_model: str = "claude-sonnet-4-20250514",
        **kwargs,
    ):
        if AsyncAnthropic is None:
            raise ImportError(
                "anthropic package is required for AnthropicClient. "
                "Install it with: pip install anthropic"
            )

        self.default_model = default_model
        
        # Resolve API key with clear priority
        resolved_api_key = self._resolve_api_key(api_key)
        
        if not resolved_api_key:
            raise AnthropicConfigurationError(
                "Anthropic API key is not configured.\n\n"
                "Configure it using one of these methods:\n"
                "  1. Set ANTHROPIC_API_KEY in your DJANGO_AGENT_RUNTIME settings:\n"
                "     DJANGO_AGENT_RUNTIME = {\n"
                "         'MODEL_PROVIDER': 'anthropic',\n"
                "         'ANTHROPIC_API_KEY': 'sk-ant-...',\n"
                "         ...\n"
                "     }\n\n"
                "  2. Set the ANTHROPIC_API_KEY environment variable:\n"
                "     export ANTHROPIC_API_KEY='sk-ant-...'\n\n"
                "  3. Pass api_key directly to get_llm_client():\n"
                "     llm = get_llm_client(api_key='sk-ant-...')"
            )
        
        self._client = AsyncAnthropic(
            api_key=resolved_api_key,
            **kwargs,
        )

    def _resolve_api_key(self, explicit_key: Optional[str]) -> Optional[str]:
        """
        Resolve API key with clear priority order.
        
        Priority:
        1. Explicit api_key parameter passed to __init__
        2. ANTHROPIC_API_KEY in DJANGO_AGENT_RUNTIME settings
        3. ANTHROPIC_API_KEY environment variable
        
        Returns:
            Resolved API key or None
        """
        if explicit_key:
            return explicit_key
        
        # Try Django settings
        try:
            from django_agent_runtime.conf import runtime_settings
            settings = runtime_settings()
            settings_key = settings.get_anthropic_api_key()
            if settings_key:
                return settings_key
        except Exception:
            pass
        
        # Fall back to environment variable
        return os.environ.get("ANTHROPIC_API_KEY")

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
    ) -> LLMResponse:
        """Generate a completion from Anthropic."""
        model = model or self.default_model

        # Extract system message
        system_message = None
        chat_messages = []
        for msg in messages:
            if msg.get("role") == "system":
                system_message = msg.get("content", "")
            else:
                chat_messages.append(self._convert_message(msg))

        # Build request
        request_kwargs = {
            "model": model,
            "messages": chat_messages,
            "max_tokens": max_tokens or 4096,
        }

        if system_message:
            request_kwargs["system"] = system_message
        if tools:
            request_kwargs["tools"] = self._convert_tools(tools)
        if temperature is not None:

            request_kwargs["temperature"] = temperature

        request_kwargs.update(kwargs)

        # Make request
        response = await self._client.messages.create(**request_kwargs)

        # Convert response
        return LLMResponse(
            message=self._convert_response(response),
            usage={
                "prompt_tokens": response.usage.input_tokens,
                "completion_tokens": response.usage.output_tokens,
                "total_tokens": response.usage.input_tokens + response.usage.output_tokens,
            },
            model=response.model,
            finish_reason=response.stop_reason or "",
            raw_response=response,
        )

    async def stream(
        self,
        messages: list[Message],
        *,
        model: Optional[str] = None,
        tools: Optional[list[dict]] = None,
        **kwargs,
    ) -> AsyncIterator[LLMStreamChunk]:
        """Stream a completion from Anthropic."""
        model = model or self.default_model

        # Extract system message
        system_message = None
        chat_messages = []
        for msg in messages:
            if msg.get("role") == "system":
                system_message = msg.get("content", "")
            else:
                chat_messages.append(self._convert_message(msg))

        request_kwargs = {
            "model": model,
            "messages": chat_messages,
            "max_tokens": kwargs.pop("max_tokens", 4096),
        }

        if system_message:
            request_kwargs["system"] = system_message
        if tools:
            request_kwargs["tools"] = self._convert_tools(tools)

        request_kwargs.update(kwargs)

        async with self._client.messages.stream(**request_kwargs) as stream:
            async for event in stream:
                if event.type == "content_block_delta":
                    if hasattr(event.delta, "text"):
                        yield LLMStreamChunk(delta=event.delta.text)
                elif event.type == "message_stop":
                    yield LLMStreamChunk(finish_reason="stop")

    def _convert_message(self, msg: Message) -> dict:
        """Convert our message format to Anthropic format."""
        role = msg.get("role", "user")
        if role == "assistant":
            role = "assistant"
        elif role == "tool":
            role = "user"  # Tool results go as user messages in Anthropic

        return {
            "role": role,
            "content": msg.get("content", ""),
        }

    def _convert_tools(self, tools: list[dict]) -> list[dict]:
        """Convert OpenAI tool format to Anthropic format."""
        result = []
        for tool in tools:
            if tool.get("type") == "function":
                func = tool["function"]
                result.append({
                    "name": func["name"],
                    "description": func.get("description", ""),
                    "input_schema": func.get("parameters", {}),
                })
        return result

    def _convert_response(self, response) -> Message:
        """Convert Anthropic response to our format."""
        content = ""
        tool_calls = []

        for block in response.content:
            if block.type == "text":
                content += block.text
            elif block.type == "tool_use":
                tool_calls.append({
                    "id": block.id,
                    "type": "function",
                    "function": {
                        "name": block.name,
                        "arguments": str(block.input),
                    },
                })

        result: Message = {
            "role": "assistant",
            "content": content,
        }

        if tool_calls:
            result["tool_calls"] = tool_calls

        return result
