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
    "OpenAIConfigurationError",
    "AnthropicConfigurationError",
]


class OpenAIConfigurationError(Exception):
    """Raised when OpenAI API key is not configured."""
    pass


class AnthropicConfigurationError(Exception):
    """Raised when Anthropic API key is not configured."""
    pass


def get_llm_client(provider: str = None, **kwargs) -> LLMClient:
    """
    Factory function to get an LLM client.

    Args:
        provider: "openai", "anthropic", "litellm", etc.
        **kwargs: Provider-specific configuration (e.g., api_key, default_model)

    Returns:
        LLMClient instance
        
    Raises:
        OpenAIConfigurationError: If OpenAI is selected but API key is not configured
        AnthropicConfigurationError: If Anthropic is selected but API key is not configured
        ValueError: If an unknown provider is specified
        
    Example:
        # Using Django settings (recommended)
        # In settings.py:
        # DJANGO_AGENT_RUNTIME = {
        #     'MODEL_PROVIDER': 'openai',
        #     'OPENAI_API_KEY': 'sk-...',
        # }
        llm = get_llm_client()
        
        # Or with explicit API key
        llm = get_llm_client(api_key='sk-...')
        
        # Or with a different provider
        llm = get_llm_client(provider='anthropic', api_key='sk-ant-...')
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
        raise ValueError(
            f"Unknown LLM provider: {provider}\n\n"
            f"Supported providers: 'openai', 'anthropic', 'litellm'\n"
            f"Set MODEL_PROVIDER in your DJANGO_AGENT_RUNTIME settings."
        )
