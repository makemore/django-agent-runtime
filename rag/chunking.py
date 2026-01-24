"""
Text chunking utilities for RAG.

This module re-exports chunking utilities from agent_runtime_core.
The implementation has been moved to the core package for portability.

For new code, import directly from agent_runtime_core.rag:
    from agent_runtime_core.rag import chunk_text, ChunkingConfig, TextChunk
"""

# Re-export from core for backwards compatibility
from agent_runtime_core.rag.chunking import (
    chunk_text,
    ChunkingConfig,
    TextChunk,
)

__all__ = [
    "chunk_text",
    "ChunkingConfig",
    "TextChunk",
]

