"""
Django Agent Runtime LLM client implementations.

This module re-exports LLM clients from agent_runtime_core and provides
Django-specific factory functions that use Django settings for configuration.

For new code, consider importing directly from agent_runtime_core.llm.
"""

from typing import Optional

# Re-export everything from agent_runtime_core.llm
from agent_runtime_core.llm import (
    # Interfaces
    LLMClient,
    LLMResponse,
    LLMStreamChunk,
    # Model config
    ModelInfo,
    SUPPORTED_MODELS,
    DEFAULT_MODEL,
    get_model_info,
    get_provider_for_model,
    list_models_for_ui,
    # Exceptions
    OpenAIConfigurationError,
    AnthropicConfigurationError,
)

# Re-export client classes (they use core interfaces now)
from agent_runtime_core.llm.openai import OpenAIClient
from agent_runtime_core.llm.anthropic import AnthropicClient

__all__ = [
    # Interfaces
    "LLMClient",
    "LLMResponse",
    "LLMStreamChunk",
    # Client classes
    "OpenAIClient",
    "AnthropicClient",
    # Factory functions (Django-specific)
    "get_llm_client",
    "get_llm_client_for_model",
    # Model config
    "ModelInfo",
    "SUPPORTED_MODELS",
    "DEFAULT_MODEL",
    "get_model_info",
    "get_provider_for_model",
    "list_models_for_ui",
    # Exceptions
    "OpenAIConfigurationError",
    "AnthropicConfigurationError",
]


def get_llm_client(
    provider: Optional[str] = None,
    model: Optional[str] = None,
    **kwargs
) -> LLMClient:
    """
    Factory function to get an LLM client using Django settings.

    Can auto-detect provider from model name if model is provided.

    Args:
        provider: "openai", "anthropic", "litellm", etc. (optional if model provided)
        model: Model ID - if provided, auto-detects provider
        **kwargs: Provider-specific configuration (e.g., api_key, default_model)

    Returns:
        LLMClient instance

    Raises:
        OpenAIConfigurationError: If OpenAI is selected but API key is not configured
        AnthropicConfigurationError: If Anthropic is selected but API key is not configured
        ValueError: If an unknown provider is specified

    Example:
        # Auto-detect from model name (recommended)
        llm = get_llm_client(model="claude-sonnet-4-20250514")
        llm = get_llm_client(model="gpt-4o")

        # Using Django settings
        llm = get_llm_client()

        # Explicit provider
        llm = get_llm_client(provider='anthropic')
    """
    from django_agent_runtime.conf import runtime_settings

    settings = runtime_settings()

    # Auto-detect provider from model name if not explicitly provided
    if provider is None and model:
        detected_provider = get_provider_for_model(model)
        if detected_provider:
            provider = detected_provider

    # Fall back to Django settings
    provider = provider or settings.MODEL_PROVIDER

    if provider == "openai":
        # Pass Django settings API key if not explicitly provided
        if "api_key" not in kwargs:
            api_key = settings.get_openai_api_key()
            if api_key:
                kwargs["api_key"] = api_key
        return OpenAIClient(**kwargs)

    elif provider == "anthropic":
        # Pass Django settings API key if not explicitly provided
        if "api_key" not in kwargs:
            api_key = settings.get_anthropic_api_key()
            if api_key:
                kwargs["api_key"] = api_key
        return AnthropicClient(**kwargs)

    elif provider == "litellm":
        if not getattr(settings, 'LITELLM_ENABLED', False):
            raise ValueError("LiteLLM is not enabled in settings")
        from agent_runtime_core.llm.litellm_client import LiteLLMClient
        return LiteLLMClient(**kwargs)

    else:
        raise ValueError(
            f"Unknown LLM provider: {provider}\n\n"
            f"Supported providers: 'openai', 'anthropic', 'litellm'\n"
            f"Set MODEL_PROVIDER in your DJANGO_AGENT_RUNTIME settings."
        )


def get_llm_client_for_model(model: str, **kwargs) -> LLMClient:
    """
    Get an LLM client configured for a specific model.

    This is a convenience function that auto-detects the provider
    and sets the default model.

    Args:
        model: Model ID (e.g., "gpt-4o", "claude-sonnet-4-20250514")
        **kwargs: Additional client configuration

    Returns:
        LLMClient configured for the specified model

    Raises:
        ValueError: If model provider cannot be determined

    Example:
        llm = get_llm_client_for_model("claude-sonnet-4-20250514")
        response = await llm.generate(messages)  # Uses claude-sonnet-4-20250514
    """
    provider = get_provider_for_model(model)
    if not provider:
        raise ValueError(
            f"Cannot determine provider for model: {model}\n"
            f"Known models: {', '.join(SUPPORTED_MODELS.keys())}"
        )

    return get_llm_client(provider=provider, default_model=model, **kwargs)
