"""
Supported LLM models configuration.

This module re-exports model configuration from agent_runtime_core.
For new code, consider importing directly from agent_runtime_core.llm.models_config.
"""

# Re-export everything from agent_runtime_core
from agent_runtime_core.llm.models_config import (
    ModelInfo,
    SUPPORTED_MODELS,
    DEFAULT_MODEL,
    get_model_info,
    get_provider_for_model,
    list_models_for_ui,
)

__all__ = [
    "ModelInfo",
    "SUPPORTED_MODELS",
    "DEFAULT_MODEL",
    "get_model_info",
    "get_provider_for_model",
    "list_models_for_ui",
]

