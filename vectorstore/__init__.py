"""
Vector store implementations for Django.

Provides PostgreSQL-based vector storage using pgvector extension.
"""

# Use lazy import to avoid circular imports and allow standalone testing
def __getattr__(name: str):
    if name == "PgVectorStore":
        from django_agent_runtime.vectorstore.pgvector import PgVectorStore
        return PgVectorStore
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "PgVectorStore",
]

