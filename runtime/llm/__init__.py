"""
LLM client implementations.

Provides:
- LLMClient: Abstract interface (from interfaces.py)
- OpenAIClient: OpenAI API client
- AnthropicClient: Anthropic API client
- LiteLLMClient: LiteLLM adapter (optional)
"""

from django_agent_runtime.runtime.interfaces import LLMClient, LLMResponse, LLMStreamChunk

__all__ = [
    "LLMClient",
    "LLMResponse",
    "LLMStreamChunk",
    "get_llm_client",
]


def get_llm_client(provider: str = None, **kwargs) -> LLMClient:
    """
    Factory function to get an LLM client.

    Args:
        provider: "openai", "anthropic", "litellm", etc.
        **kwargs: Provider-specific configuration

    Returns:
        LLMClient instance
    """
    from django_agent_runtime.conf import runtime_settings

    settings = runtime_settings()
    provider = provider or settings.MODEL_PROVIDER

    if provider == "openai":
        from django_agent_runtime.runtime.llm.openai import OpenAIClient

        return OpenAIClient(**kwargs)

    elif provider == "anthropic":
        from django_agent_runtime.runtime.llm.anthropic import AnthropicClient

        return AnthropicClient(**kwargs)

    elif provider == "litellm":
        if not settings.LITELLM_ENABLED:
            raise ValueError("LiteLLM is not enabled in settings")
        from django_agent_runtime.runtime.llm.litellm_adapter import LiteLLMClient

        return LiteLLMClient(**kwargs)

    else:
        raise ValueError(f"Unknown LLM provider: {provider}")

