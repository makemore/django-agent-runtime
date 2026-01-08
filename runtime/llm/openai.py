"""
OpenAI API client implementation.
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
    from openai import AsyncOpenAI, OpenAIError
except ImportError:
    AsyncOpenAI = None
    OpenAIError = None


class OpenAIConfigurationError(Exception):
    """Raised when OpenAI API key is not configured."""
    pass


class OpenAIClient(LLMClient):
    """
    OpenAI API client.

    Supports GPT-4, GPT-3.5, and other OpenAI models.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        default_model: str = "gpt-4o",
        organization: Optional[str] = None,
        base_url: Optional[str] = None,
        **kwargs,
    ):
        if AsyncOpenAI is None:
            raise ImportError(
                "openai package is required for OpenAIClient. "
                "Install it with: pip install openai"
            )

        self.default_model = default_model
        
        # Resolve API key with clear priority
        resolved_api_key = self._resolve_api_key(api_key)
        
        try:
            self._client = AsyncOpenAI(
                api_key=resolved_api_key,
                organization=organization,
                base_url=base_url,
                **kwargs,
            )
        except OpenAIError as e:
            if "api_key" in str(e).lower():
                raise OpenAIConfigurationError(
                    "OpenAI API key is not configured.\n\n"
                    "Configure it using one of these methods:\n"
                    "  1. Set OPENAI_API_KEY in your DJANGO_AGENT_RUNTIME settings:\n"
                    "     DJANGO_AGENT_RUNTIME = {\n"
                    "         'OPENAI_API_KEY': 'sk-...',\n"
                    "         ...\n"
                    "     }\n\n"
                    "  2. Set the OPENAI_API_KEY environment variable:\n"
                    "     export OPENAI_API_KEY='sk-...'\n\n"
                    "  3. Pass api_key directly to get_llm_client():\n"
                    "     llm = get_llm_client(api_key='sk-...')"
                ) from e
            raise

    def _resolve_api_key(self, explicit_key: Optional[str]) -> Optional[str]:
        """
        Resolve API key with clear priority order.
        
        Priority:
        1. Explicit api_key parameter passed to __init__
        2. OPENAI_API_KEY in DJANGO_AGENT_RUNTIME settings
        3. OPENAI_API_KEY environment variable
        
        Returns:
            Resolved API key or None (let OpenAI client raise its own error)
        """
        if explicit_key:
            return explicit_key
        
        # Try Django settings
        try:
            from django_agent_runtime.conf import runtime_settings
            settings = runtime_settings()
            settings_key = settings.get_openai_api_key()
            if settings_key:
                return settings_key
        except Exception:
            pass
        
        # Fall back to environment variable (OpenAI client will also check this)
        return os.environ.get("OPENAI_API_KEY")

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
        """Generate a completion from OpenAI."""
        model = model or self.default_model

        # Build request
        request_kwargs = {
            "model": model,
            "messages": self._convert_messages(messages),
        }

        if tools:
            request_kwargs["tools"] = tools
        if temperature is not None:
            request_kwargs["temperature"] = temperature
        if max_tokens is not None:
            request_kwargs["max_tokens"] = max_tokens

        request_kwargs.update(kwargs)

        # Make request
        response = await self._client.chat.completions.create(**request_kwargs)

        # Convert response
        choice = response.choices[0]
        message = choice.message

        return LLMResponse(
            message=self._convert_response_message(message),
            usage={
                "prompt_tokens": response.usage.prompt_tokens if response.usage else 0,
                "completion_tokens": response.usage.completion_tokens if response.usage else 0,
                "total_tokens": response.usage.total_tokens if response.usage else 0,
            },
            model=response.model,
            finish_reason=choice.finish_reason or "",
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
        """Stream a completion from OpenAI."""
        model = model or self.default_model

        request_kwargs = {
            "model": model,
            "messages": self._convert_messages(messages),
            "stream": True,
        }

        if tools:
            request_kwargs["tools"] = tools

        request_kwargs.update(kwargs)

        async with await self._client.chat.completions.create(**request_kwargs) as stream:
            async for chunk in stream:
                if not chunk.choices:
                    continue

                choice = chunk.choices[0]
                delta = choice.delta

                yield LLMStreamChunk(
                    delta=delta.content or "",
                    tool_calls=delta.tool_calls if hasattr(delta, "tool_calls") else None,
                    finish_reason=choice.finish_reason,
                    usage=None,  # Usage comes in final chunk for some models
                )

    def _convert_messages(self, messages: list[Message]) -> list[dict]:
        """Convert our message format to OpenAI format."""
        result = []
        for msg in messages:
            converted = {
                "role": msg.get("role", "user"),
                "content": msg.get("content", ""),
            }

            if msg.get("name"):
                converted["name"] = msg["name"]
            if msg.get("tool_call_id"):
                converted["tool_call_id"] = msg["tool_call_id"]
            if msg.get("tool_calls"):
                converted["tool_calls"] = msg["tool_calls"]

            result.append(converted)

        return result

    def _convert_response_message(self, message) -> Message:
        """Convert OpenAI response message to our format."""
        result: Message = {
            "role": message.role,
            "content": message.content or "",
        }

        if message.tool_calls:
            result["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": tc.type,
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments,
                    },
                }
                for tc in message.tool_calls
            ]

        return result
