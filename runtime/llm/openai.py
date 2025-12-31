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
    from openai import AsyncOpenAI
except ImportError:
    AsyncOpenAI = None


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
            raise ImportError("openai package is required for OpenAIClient")

        self.default_model = default_model
        self._client = AsyncOpenAI(
            api_key=api_key or os.environ.get("OPENAI_API_KEY"),
            organization=organization,
            base_url=base_url,
            **kwargs,
        )

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

