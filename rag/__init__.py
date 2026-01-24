"""
RAG (Retrieval Augmented Generation) services for django_agent_runtime.

This module provides Django-specific adapters for RAG:
- KnowledgeIndexer: Django adapter for indexing with model integration
- KnowledgeRetriever: Django adapter for retrieval with settings integration
- Text chunking utilities (re-exported from agent_runtime_core)

For standalone Python usage without Django, use agent_runtime_core.rag directly:
    from agent_runtime_core.rag import KnowledgeIndexer, KnowledgeRetriever
"""

# Re-export chunking from core (no Django dependency)
from agent_runtime_core.rag import (
    chunk_text,
    ChunkingConfig,
    TextChunk,
)


# Use lazy imports for Django-specific classes to avoid circular dependencies
def __getattr__(name: str):
    if name == "KnowledgeIndexer":
        from django_agent_runtime.rag.indexer import KnowledgeIndexer
        return KnowledgeIndexer
    elif name == "KnowledgeRetriever":
        from django_agent_runtime.rag.retriever import KnowledgeRetriever
        return KnowledgeRetriever
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    # Django adapters
    "KnowledgeIndexer",
    "KnowledgeRetriever",
    # Re-exported from core
    "chunk_text",
    "ChunkingConfig",
    "TextChunk",
]

