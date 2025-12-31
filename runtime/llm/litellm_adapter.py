"""
LiteLLM adapter for unified LLM access.

LiteLLM provides a unified interface to 100+ LLM providers.
This is an OPTIONAL adapter - the core runtime doesn't depend on it.
"""

from typing import AsyncIterator, Optional

from django_agent_runtime.runtime.interfaces import (
    LLMClient,
    LLMResponse,
    LLMStreamChunk,
    Message,
)

try:
    import litellm
    from litellm import acompletion
except ImportError:
    litellm = None
    acompletion = None


class LiteLLMClient(LLMClient):
    """
    LiteLLM adapter for unified LLM access.

    Supports 100+ providers through LiteLLM's unified interface.
    See: https://docs.litellm.ai/docs/providers
    """

    def __init__(
        self,
        default_model: str = "gpt-4o",
        **kwargs,
    ):
        if litellm is None:
            raise ImportError("litellm package is required for LiteLLMClient")

        self.default_model = default_model
        self._kwargs = kwargs

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
        """Generate a completion using LiteLLM."""
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

        request_kwargs.update(self._kwargs)
        request_kwargs.update(kwargs)

        # Make request
        response = await acompletion(**request_kwargs)

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
            model=response.model or model,
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
        """Stream a completion using LiteLLM."""
        model = model or self.default_model

        request_kwargs = {
            "model": model,
            "messages": self._convert_messages(messages),
            "stream": True,
        }

        if tools:
            request_kwargs["tools"] = tools

        request_kwargs.update(self._kwargs)
        request_kwargs.update(kwargs)

        response = await acompletion(**request_kwargs)

        async for chunk in response:
            if not chunk.choices:
                continue

            choice = chunk.choices[0]
            delta = choice.delta

            yield LLMStreamChunk(
                delta=getattr(delta, "content", "") or "",
                tool_calls=getattr(delta, "tool_calls", None),
                finish_reason=choice.finish_reason,
                usage=None,
            )

    def _convert_messages(self, messages: list[Message]) -> list[dict]:
        """Convert our message format to LiteLLM format (OpenAI-compatible)."""
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
        """Convert LiteLLM response message to our format."""
        result: Message = {
            "role": message.role,
            "content": message.content or "",
        }

        if hasattr(message, "tool_calls") and message.tool_calls:
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

