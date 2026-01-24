"""
Django-specific knowledge retrieval service for RAG.

This module provides a Django adapter for the core KnowledgeRetriever,
adding Django model integration and settings-based configuration.

For standalone Python usage without Django, use:
    from agent_runtime_core.rag import KnowledgeRetriever
"""

import logging
from typing import Optional

from asgiref.sync import sync_to_async
from django.conf import settings

from agent_runtime_core.rag import KnowledgeRetriever as CoreKnowledgeRetriever

logger = logging.getLogger(__name__)


class KnowledgeRetriever:
    """
    Django adapter for knowledge retrieval.

    Wraps the core KnowledgeRetriever and adds:
    - Django settings integration for configuration
    - AgentDefinition model integration for RAG config
    - Agent-specific filtering

    For standalone Python usage, use agent_runtime_core.rag.KnowledgeRetriever directly.

    Usage:
        retriever = KnowledgeRetriever()
        context = await retriever.retrieve(
            agent_id="...",
            query="What is the return policy?",
            top_k=5,
        )
    """

    def __init__(
        self,
        vector_store=None,
        embedding_client=None,
    ):
        """
        Initialize the retriever.

        Args:
            vector_store: Optional VectorStore instance
            embedding_client: Optional EmbeddingClient instance
        """
        self._vector_store = vector_store
        self._embedding_client = embedding_client
        self._core_retriever: Optional[CoreKnowledgeRetriever] = None
        self._initialized = False

    def _ensure_initialized(self):
        """Lazily initialize vector store and embedding client."""
        if self._initialized:
            return

        if self._vector_store is None:
            self._vector_store = self._create_vector_store()

        if self._embedding_client is None:
            self._embedding_client = self._create_embedding_client()

        # Create core retriever
        self._core_retriever = CoreKnowledgeRetriever(
            vector_store=self._vector_store,
            embedding_client=self._embedding_client,
        )

        self._initialized = True

    def _create_vector_store(self):
        """Create vector store from Django settings."""
        from agent_runtime_core.vectorstore import get_vector_store

        rag_settings = getattr(settings, 'AGENT_RAG', {})
        backend = rag_settings.get('VECTOR_STORE_BACKEND', 'sqlite_vec')

        if backend == 'sqlite_vec':
            path = rag_settings.get('SQLITE_VEC_PATH', './agent_vectors.db')
            return get_vector_store('sqlite_vec', path=path)
        elif backend == 'pgvector':
            from django_agent_runtime.vectorstore import PgVectorStore
            return PgVectorStore()
        else:
            return get_vector_store(backend, **rag_settings.get('VECTOR_STORE_OPTIONS', {}))

    def _create_embedding_client(self):
        """Create embedding client from Django settings."""
        from agent_runtime_core.vectorstore import get_embedding_client

        rag_settings = getattr(settings, 'AGENT_RAG', {})
        provider = rag_settings.get('EMBEDDING_PROVIDER', 'openai')
        model = rag_settings.get('EMBEDDING_MODEL', 'text-embedding-3-small')

        return get_embedding_client(provider, model=model)

    async def retrieve(
        self,
        agent_id: str,
        query: str,
        top_k: int = 5,
        similarity_threshold: float = 0.0,
        knowledge_ids: Optional[list[str]] = None,
    ) -> list[dict]:
        """
        Retrieve relevant knowledge chunks for a query.

        Args:
            agent_id: UUID of the agent to retrieve knowledge for
            query: The user's query to find relevant content for
            top_k: Maximum number of chunks to retrieve
            similarity_threshold: Minimum similarity score (0-1)
            knowledge_ids: Optional list of specific knowledge IDs to search

        Returns:
            List of dicts with retrieved chunks and metadata
        """
        self._ensure_initialized()

        # Use core retriever with agent_id filter
        results = await self._core_retriever.retrieve(
            query=query,
            top_k=top_k,
            similarity_threshold=similarity_threshold,
            filter={'agent_id': str(agent_id)},
        )

        # Convert to dict format for backwards compatibility
        return [
            {
                'content': r.content,
                'score': r.score,
                'knowledge_id': r.metadata.get('knowledge_id'),
                'knowledge_name': r.metadata.get('name') or r.metadata.get('knowledge_name'),
                'chunk_index': r.chunk_index,
            }
            for r in results
        ]
    
    async def retrieve_for_agent(
        self,
        agent_id: str,
        query: str,
        rag_config: Optional[dict] = None,
    ) -> str:
        """
        Retrieve and format knowledge for inclusion in agent prompt.
        
        This is the main method called by the agent runtime.
        
        Args:
            agent_id: UUID of the agent
            query: The user's message/query
            rag_config: Optional RAG configuration override
            
        Returns:
            Formatted string of retrieved knowledge for prompt inclusion
        """
        from django_agent_runtime.models import AgentDefinition
        
        # Get agent's RAG config if not provided
        if rag_config is None:
            try:
                agent = await sync_to_async(AgentDefinition.objects.get)(id=agent_id)
                rag_config = agent.rag_config or {}
            except AgentDefinition.DoesNotExist:
                rag_config = {}

        # Check if RAG is enabled
        if not rag_config.get('enabled', True):
            return ""

        # Get retrieval parameters
        top_k = rag_config.get('top_k', 5)
        similarity_threshold = rag_config.get('similarity_threshold', 0.0)

        # Retrieve relevant chunks
        results = await self.retrieve(
            agent_id=agent_id,
            query=query,
            top_k=top_k,
            similarity_threshold=similarity_threshold,
        )

        if not results:
            return ""

        # Format for prompt inclusion
        return self._format_for_prompt(results)

    def _format_for_prompt(self, results: list[dict]) -> str:
        """Format retrieved results for inclusion in the prompt."""
        if not results:
            return ""

        parts = ["## Relevant Knowledge\n"]
        parts.append("The following information may be relevant to the user's question:\n")

        # Group by knowledge source
        by_source = {}
        for r in results:
            source = r.get('knowledge_name', 'Unknown')
            if source not in by_source:
                by_source[source] = []
            by_source[source].append(r)

        for source, chunks in by_source.items():
            parts.append(f"\n### {source}\n")
            for chunk in chunks:
                parts.append(f"{chunk['content']}\n")

        return "\n".join(parts)

    async def preview_search(
        self,
        agent_id: str,
        query: str,
        top_k: int = 10,
    ) -> dict:
        """
        Preview search results for debugging/testing.

        Returns detailed results including scores and metadata.
        """
        results = await self.retrieve(
            agent_id=agent_id,
            query=query,
            top_k=top_k,
            similarity_threshold=0.0,  # Return all for preview
        )

        return {
            'query': query,
            'agent_id': str(agent_id),
            'results': results,
            'total_results': len(results),
        }

