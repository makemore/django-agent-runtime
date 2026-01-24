"""
Django-specific knowledge indexing service for RAG.

This module provides a Django adapter for the core KnowledgeIndexer,
adding Django model integration and settings-based configuration.

For standalone Python usage without Django, use:
    from agent_runtime_core.rag import KnowledgeIndexer
"""

import logging
from typing import Optional

from asgiref.sync import sync_to_async
from django.conf import settings
from django.utils import timezone

from agent_runtime_core.rag import KnowledgeIndexer as CoreKnowledgeIndexer
from agent_runtime_core.rag.chunking import ChunkingConfig

logger = logging.getLogger(__name__)


class KnowledgeIndexer:
    """
    Django adapter for knowledge indexing.

    Wraps the core KnowledgeIndexer and adds:
    - Django settings integration for configuration
    - AgentKnowledge model status tracking
    - Agent-level batch indexing

    For standalone Python usage, use agent_runtime_core.rag.KnowledgeIndexer directly.

    Usage:
        indexer = KnowledgeIndexer()
        await indexer.index_knowledge(knowledge_id)

        # Or index all pending for an agent
        await indexer.index_agent_knowledge(agent_id)
    """

    def __init__(
        self,
        vector_store=None,
        embedding_client=None,
    ):
        """
        Initialize the indexer.

        Args:
            vector_store: Optional VectorStore instance. If not provided,
                         will be created from settings.
            embedding_client: Optional EmbeddingClient instance. If not provided,
                             will be created from settings.
        """
        self._vector_store = vector_store
        self._embedding_client = embedding_client
        self._core_indexer: Optional[CoreKnowledgeIndexer] = None
        self._initialized = False

    def _ensure_initialized(self):
        """Lazily initialize vector store and embedding client."""
        if self._initialized:
            return

        if self._vector_store is None:
            self._vector_store = self._create_vector_store()

        if self._embedding_client is None:
            self._embedding_client = self._create_embedding_client()

        # Create core indexer
        self._core_indexer = CoreKnowledgeIndexer(
            vector_store=self._vector_store,
            embedding_client=self._embedding_client,
        )

        self._initialized = True

    def _create_vector_store(self):
        """Create vector store from Django settings."""
        from agent_runtime_core.vectorstore import get_vector_store

        # Get settings from Django settings or defaults
        rag_settings = getattr(settings, 'AGENT_RAG', {})
        backend = rag_settings.get('VECTOR_STORE_BACKEND', 'sqlite_vec')

        if backend == 'sqlite_vec':
            path = rag_settings.get('SQLITE_VEC_PATH', './agent_vectors.db')
            return get_vector_store('sqlite_vec', path=path)
        elif backend == 'pgvector':
            # Use Django's database connection
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
    
    async def index_knowledge(
        self,
        knowledge_id: str,
        force: bool = False,
    ) -> dict:
        """
        Index a single knowledge source (Django model).

        Args:
            knowledge_id: UUID of the AgentKnowledge record
            force: If True, re-index even if already indexed

        Returns:
            Dict with indexing results
        """
        from django_agent_runtime.models import AgentKnowledge

        self._ensure_initialized()

        # Get the knowledge record
        knowledge = await sync_to_async(AgentKnowledge.objects.get)(id=knowledge_id)

        # Check if indexing is needed
        if not force and knowledge.embedding_status == 'indexed':
            if not knowledge.needs_reindexing():
                return {
                    'status': 'skipped',
                    'message': 'Already indexed and up to date',
                    'knowledge_id': str(knowledge_id),
                }

        # Update status to indexing
        knowledge.embedding_status = 'indexing'
        knowledge.embedding_error = ''
        await sync_to_async(knowledge.save)(update_fields=['embedding_status', 'embedding_error'])

        try:
            # Get content to index
            content = knowledge.get_indexable_content()
            if not content:
                raise ValueError("No content to index")

            # Get chunking config from knowledge and agent settings
            rag_config = knowledge.rag_config or {}
            agent_rag_config = knowledge.agent.rag_config or {}

            chunking_config = ChunkingConfig(
                chunk_size=rag_config.get('chunk_size', agent_rag_config.get('chunk_size', 500)),
                chunk_overlap=rag_config.get('chunk_overlap', agent_rag_config.get('chunk_overlap', 50)),
            )

            # Use core indexer to index the content
            # We use knowledge_id as source_id for filtering
            result = await self._core_indexer.index_text(
                text=content,
                source_id=str(knowledge_id),
                metadata={
                    'knowledge_id': str(knowledge.id),
                    'agent_id': str(knowledge.agent_id),
                    'name': knowledge.name,
                },
                chunking_config=chunking_config,
                force=force,
            )

            if result.status == 'error':
                raise ValueError(result.error)

            # Update knowledge record with success
            knowledge.embedding_status = 'indexed'
            knowledge.chunk_count = result.chunks_indexed
            knowledge.content_hash = knowledge.get_content_hash()
            knowledge.indexed_at = timezone.now()
            await sync_to_async(knowledge.save)(
                update_fields=['embedding_status', 'chunk_count', 'content_hash', 'indexed_at']
            )

            return {
                'status': 'success',
                'knowledge_id': str(knowledge_id),
                'chunks_indexed': result.chunks_indexed,
            }

        except Exception as e:
            logger.exception(f"Error indexing knowledge {knowledge_id}")
            knowledge.embedding_status = 'failed'
            knowledge.embedding_error = str(e)
            await sync_to_async(knowledge.save)(
                update_fields=['embedding_status', 'embedding_error']
            )
            return {
                'status': 'error',
                'knowledge_id': str(knowledge_id),
                'error': str(e),
            }

    async def index_agent_knowledge(
        self,
        agent_id: str,
        force: bool = False,
    ) -> dict:
        """
        Index all RAG knowledge sources for an agent.

        Args:
            agent_id: UUID of the AgentDefinition
            force: If True, re-index all even if already indexed

        Returns:
            Dict with indexing results for all knowledge sources
        """
        from django_agent_runtime.models import AgentKnowledge

        # Get all RAG knowledge for this agent
        knowledge_qs = AgentKnowledge.objects.filter(
            agent_id=agent_id,
            inclusion_mode='rag',
            is_active=True,
        )

        if not force:
            # Only index those that need it
            knowledge_qs = knowledge_qs.exclude(embedding_status='indexed')

        knowledge_list = await sync_to_async(list)(knowledge_qs)

        results = {
            'agent_id': str(agent_id),
            'total': len(knowledge_list),
            'indexed': [],
            'skipped': [],
            'errors': [],
        }

        for knowledge in knowledge_list:
            result = await self.index_knowledge(str(knowledge.id), force=force)
            if result['status'] == 'success':
                results['indexed'].append(result)
            elif result['status'] == 'skipped':
                results['skipped'].append(result)
            else:
                results['errors'].append(result)

        return results

    async def delete_knowledge_vectors(self, knowledge_id: str) -> dict:
        """
        Delete all vectors for a knowledge source.

        Call this when a knowledge source is deleted or changed from RAG mode.
        """
        from django_agent_runtime.models import AgentKnowledge

        self._ensure_initialized()

        try:
            # Use core indexer to delete vectors
            await self._core_indexer.delete_source(str(knowledge_id))

            # Update knowledge record if it still exists
            try:
                knowledge = await sync_to_async(AgentKnowledge.objects.get)(id=knowledge_id)
                knowledge.embedding_status = 'not_indexed'
                knowledge.chunk_count = 0
                knowledge.indexed_at = None
                await sync_to_async(knowledge.save)(
                    update_fields=['embedding_status', 'chunk_count', 'indexed_at']
                )
            except AgentKnowledge.DoesNotExist:
                pass

            return {'status': 'success', 'knowledge_id': str(knowledge_id)}
        except Exception as e:
            logger.exception(f"Error deleting vectors for knowledge {knowledge_id}")
            return {'status': 'error', 'knowledge_id': str(knowledge_id), 'error': str(e)}

    async def get_indexing_status(self, agent_id: str) -> dict:
        """Get indexing status for all RAG knowledge of an agent."""
        from django_agent_runtime.models import AgentKnowledge

        knowledge_list = await sync_to_async(list)(
            AgentKnowledge.objects.filter(
                agent_id=agent_id,
                inclusion_mode='rag',
                is_active=True,
            ).values('id', 'name', 'embedding_status', 'chunk_count', 'indexed_at', 'embedding_error')
        )

        return {
            'agent_id': str(agent_id),
            'knowledge_sources': [
                {
                    'id': str(k['id']),
                    'name': k['name'],
                    'status': k['embedding_status'],
                    'chunk_count': k['chunk_count'],
                    'indexed_at': k['indexed_at'].isoformat() if k['indexed_at'] else None,
                    'error': k['embedding_error'] or None,
                }
                for k in knowledge_list
            ],
        }

