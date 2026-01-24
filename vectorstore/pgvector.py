"""
PostgreSQL pgvector vector store implementation.

Uses PostgreSQL with the pgvector extension for production-grade vector storage
and similarity search. Ideal for Django applications already using PostgreSQL.

Requires: pip install pgvector psycopg[binary]
"""

import json
from typing import Optional

from agent_runtime_core.vectorstore.base import (
    VectorStore,
    VectorRecord,
    VectorSearchResult,
)


class PgVectorStore(VectorStore):
    """
    Vector store using PostgreSQL with pgvector extension.

    This implementation uses PostgreSQL's pgvector extension for efficient
    vector similarity search. It's ideal for:
    - Production Django applications
    - Applications already using PostgreSQL
    - Medium to large datasets (millions of vectors)

    The store can operate in two modes:
    1. Django ORM mode (default): Uses Django models for storage
    2. Raw connection mode: Uses a direct psycopg connection

    For Django ORM mode, ensure you've run migrations to create the
    VectorEmbedding model table.
    """

    def __init__(
        self,
        connection_string: Optional[str] = None,
        table_name: str = "agent_vectors",
        user=None,
        use_django_orm: bool = True,
    ):
        """
        Initialize PgVector store.

        Args:
            connection_string: PostgreSQL connection string (for raw mode)
            table_name: Table name for raw mode
            user: Django user for ORM mode (enables user-scoped vectors)
            use_django_orm: Whether to use Django ORM (default: True)
        """
        self._connection_string = connection_string
        self._table_name = table_name
        self._user = user
        self._use_django_orm = use_django_orm
        self._conn = None
        self._dimensions: Optional[int] = None

    def _get_connection(self):
        """Get or create the database connection for raw mode."""
        if self._conn is None:
            if self._connection_string is None:
                raise ValueError(
                    "connection_string required for raw mode. "
                    "Set use_django_orm=True to use Django's database connection."
                )
            try:
                import psycopg
                from pgvector.psycopg import register_vector
            except ImportError:
                raise ImportError(
                    "pgvector and psycopg packages not installed. "
                    "Install with: pip install pgvector psycopg[binary]"
                )
            self._conn = psycopg.connect(self._connection_string)
            register_vector(self._conn)
        return self._conn

    def _ensure_table(self, dimensions: int) -> None:
        """Ensure the vector table exists (raw mode only)."""
        if self._use_django_orm:
            return

        conn = self._get_connection()
        self._dimensions = dimensions

        with conn.cursor() as cur:
            # Enable pgvector extension
            cur.execute("CREATE EXTENSION IF NOT EXISTS vector")

            # Create table
            cur.execute(f"""
                CREATE TABLE IF NOT EXISTS {self._table_name} (
                    id TEXT PRIMARY KEY,
                    embedding vector({dimensions}),
                    content TEXT NOT NULL,
                    metadata JSONB NOT NULL DEFAULT '{{}}'::jsonb,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Create index for similarity search
            cur.execute(f"""
                CREATE INDEX IF NOT EXISTS {self._table_name}_embedding_idx
                ON {self._table_name}
                USING ivfflat (embedding vector_cosine_ops)
                WITH (lists = 100)
            """)

        conn.commit()

    async def add(
        self,
        id: str,
        vector: list[float],
        content: str,
        metadata: Optional[dict] = None,
    ) -> None:
        """Add a vector with its content and metadata."""
        if self._use_django_orm:
            await self._add_django(id, vector, content, metadata)
        else:
            await self._add_raw(id, vector, content, metadata)

    async def _add_django(
        self,
        id: str,
        vector: list[float],
        content: str,
        metadata: Optional[dict] = None,
    ) -> None:
        """Add using Django ORM."""
        from django_agent_runtime.vectorstore.models import VectorEmbedding

        defaults = {
            "embedding": vector,
            "content": content,
            "metadata": metadata or {},
        }
        if self._user:
            defaults["user"] = self._user

        await VectorEmbedding.objects.aupdate_or_create(
            vector_id=id,
            defaults=defaults,
        )

    async def _add_raw(
        self,
        id: str,
        vector: list[float],
        content: str,
        metadata: Optional[dict] = None,
    ) -> None:
        """Add using raw connection."""
        self._ensure_table(len(vector))
        conn = self._get_connection()

        with conn.cursor() as cur:
            cur.execute(
                f"""
                INSERT INTO {self._table_name} (id, embedding, content, metadata)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET
                    embedding = EXCLUDED.embedding,
                    content = EXCLUDED.content,
                    metadata = EXCLUDED.metadata
                """,
                (id, vector, content, json.dumps(metadata or {})),
            )
        conn.commit()

    async def add_batch(
        self,
        items: list[tuple[str, list[float], str, Optional[dict]]],
    ) -> None:
        """Add multiple vectors efficiently."""
        if not items:
            return

        if self._use_django_orm:
            await self._add_batch_django(items)
        else:
            await self._add_batch_raw(items)

    async def _add_batch_django(
        self,
        items: list[tuple[str, list[float], str, Optional[dict]]],
    ) -> None:
        """Add batch using Django ORM."""
        from django_agent_runtime.vectorstore.models import VectorEmbedding

        for id, vector, content, metadata in items:
            defaults = {
                "embedding": vector,
                "content": content,
                "metadata": metadata or {},
            }
            if self._user:
                defaults["user"] = self._user

            await VectorEmbedding.objects.aupdate_or_create(
                vector_id=id,
                defaults=defaults,
            )

    async def _add_batch_raw(
        self,
        items: list[tuple[str, list[float], str, Optional[dict]]],
    ) -> None:
        """Add batch using raw connection."""
        if not items:
            return

        self._ensure_table(len(items[0][1]))
        conn = self._get_connection()

        with conn.cursor() as cur:
            for id, vector, content, metadata in items:
                cur.execute(
                    f"""
                    INSERT INTO {self._table_name} (id, embedding, content, metadata)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (id) DO UPDATE SET
                        embedding = EXCLUDED.embedding,
                        content = EXCLUDED.content,
                        metadata = EXCLUDED.metadata
                    """,
                    (id, vector, content, json.dumps(metadata or {})),
                )
        conn.commit()

    async def search(
        self,
        query_vector: list[float],
        limit: int = 10,
        filter: Optional[dict] = None,
    ) -> list[VectorSearchResult]:
        """Search for similar vectors."""
        if self._use_django_orm:
            return await self._search_django(query_vector, limit, filter)
        else:
            return await self._search_raw(query_vector, limit, filter)

    async def _search_django(
        self,
        query_vector: list[float],
        limit: int = 10,
        filter: Optional[dict] = None,
    ) -> list[VectorSearchResult]:
        """Search using Django ORM."""
        from django_agent_runtime.vectorstore.models import VectorEmbedding
        from pgvector.django import CosineDistance

        qs = VectorEmbedding.objects.annotate(
            distance=CosineDistance("embedding", query_vector)
        ).order_by("distance")

        if self._user:
            qs = qs.filter(user=self._user)

        # Apply metadata filters
        if filter:
            for key, value in filter.items():
                qs = qs.filter(**{f"metadata__{key}": value})

        results = []
        async for obj in qs[:limit]:
            # Convert distance to similarity score
            score = 1.0 - obj.distance
            results.append(
                VectorSearchResult(
                    id=obj.vector_id,
                    content=obj.content,
                    score=score,
                    metadata=obj.metadata,
                )
            )
        return results

    async def _search_raw(
        self,
        query_vector: list[float],
        limit: int = 10,
        filter: Optional[dict] = None,
    ) -> list[VectorSearchResult]:
        """Search using raw connection."""
        conn = self._get_connection()

        # Build filter conditions
        filter_sql = ""
        filter_values = []
        if filter:
            conditions = []
            for key, value in filter.items():
                conditions.append(f"metadata->>'{key}' = %s")
                filter_values.append(str(value))
            filter_sql = "WHERE " + " AND ".join(conditions)

        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT id, content, metadata, embedding <=> %s AS distance
                FROM {self._table_name}
                {filter_sql}
                ORDER BY distance
                LIMIT %s
                """,
                [query_vector] + filter_values + [limit],
            )
            rows = cur.fetchall()

        results = []
        for row in rows:
            id, content, metadata, distance = row
            score = 1.0 - distance
            results.append(
                VectorSearchResult(
                    id=id,
                    content=content,
                    score=score,
                    metadata=metadata if isinstance(metadata, dict) else json.loads(metadata),
                )
            )
        return results

    async def delete(self, id: str) -> bool:
        """Delete a vector by ID."""
        if self._use_django_orm:
            return await self._delete_django(id)
        else:
            return await self._delete_raw(id)

    async def _delete_django(self, id: str) -> bool:
        """Delete using Django ORM."""
        from django_agent_runtime.vectorstore.models import VectorEmbedding

        qs = VectorEmbedding.objects.filter(vector_id=id)
        if self._user:
            qs = qs.filter(user=self._user)

        deleted, _ = await qs.adelete()
        return deleted > 0

    async def _delete_raw(self, id: str) -> bool:
        """Delete using raw connection."""
        conn = self._get_connection()

        with conn.cursor() as cur:
            cur.execute(
                f"DELETE FROM {self._table_name} WHERE id = %s",
                (id,),
            )
            deleted = cur.rowcount > 0
        conn.commit()
        return deleted

    async def delete_by_filter(self, filter: dict) -> int:
        """Delete vectors matching filter."""
        if self._use_django_orm:
            return await self._delete_by_filter_django(filter)
        else:
            return await self._delete_by_filter_raw(filter)

    async def _delete_by_filter_django(self, filter: dict) -> int:
        """Delete by filter using Django ORM."""
        from django_agent_runtime.vectorstore.models import VectorEmbedding

        qs = VectorEmbedding.objects.all()
        if self._user:
            qs = qs.filter(user=self._user)

        for key, value in filter.items():
            qs = qs.filter(**{f"metadata__{key}": value})

        deleted, _ = await qs.adelete()
        return deleted

    async def _delete_by_filter_raw(self, filter: dict) -> int:
        """Delete by filter using raw connection."""
        conn = self._get_connection()

        conditions = []
        values = []
        for key, value in filter.items():
            conditions.append(f"metadata->>'{key}' = %s")
            values.append(str(value))

        filter_sql = " AND ".join(conditions)

        with conn.cursor() as cur:
            cur.execute(
                f"DELETE FROM {self._table_name} WHERE {filter_sql}",
                values,
            )
            deleted = cur.rowcount
        conn.commit()
        return deleted

    async def get(self, id: str) -> Optional[VectorRecord]:
        """Get a vector by ID."""
        if self._use_django_orm:
            return await self._get_django(id)
        else:
            return await self._get_raw(id)

    async def _get_django(self, id: str) -> Optional[VectorRecord]:
        """Get using Django ORM."""
        from django_agent_runtime.vectorstore.models import VectorEmbedding

        qs = VectorEmbedding.objects.filter(vector_id=id)
        if self._user:
            qs = qs.filter(user=self._user)

        try:
            obj = await qs.afirst()
            if obj is None:
                return None

            return VectorRecord(
                id=obj.vector_id,
                vector=list(obj.embedding) if obj.embedding else [],
                content=obj.content,
                metadata=obj.metadata,
            )
        except Exception:
            return None

    async def _get_raw(self, id: str) -> Optional[VectorRecord]:
        """Get using raw connection."""
        conn = self._get_connection()

        with conn.cursor() as cur:
            cur.execute(
                f"SELECT id, embedding, content, metadata FROM {self._table_name} WHERE id = %s",
                (id,),
            )
            row = cur.fetchone()

        if row is None:
            return None

        id, embedding, content, metadata = row
        return VectorRecord(
            id=id,
            vector=list(embedding) if embedding else [],
            content=content,
            metadata=metadata if isinstance(metadata, dict) else json.loads(metadata),
        )

    async def close(self) -> None:
        """Close the database connection."""
        if self._conn is not None:
            self._conn.close()
            self._conn = None
