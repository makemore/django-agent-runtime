"""
Django models for vector storage using pgvector.

These models provide ORM integration for vector storage and similarity search.
Requires: pip install pgvector psycopg[binary]
"""

from django.db import models
from django.contrib.auth import get_user_model

try:
    from pgvector.django import VectorField
except ImportError:
    # Provide a fallback for when pgvector is not installed
    VectorField = None


class VectorEmbedding(models.Model):
    """
    Django model for storing vector embeddings with pgvector.

    This model stores vectors along with their content and metadata,
    enabling similarity search through PostgreSQL's pgvector extension.
    """

    # Primary identifier
    vector_id = models.CharField(max_length=255, unique=True, db_index=True)

    # The embedding vector (dimensions set at migration time)
    # Default to 1536 dimensions (OpenAI text-embedding-3-small)
    if VectorField is not None:
        embedding = VectorField(dimensions=1536)
    else:
        # Fallback when pgvector is not installed
        embedding = models.BinaryField(null=True)

    # Content and metadata
    content = models.TextField()
    metadata = models.JSONField(default=dict)

    # Optional user association for multi-tenant scenarios
    user = models.ForeignKey(
        get_user_model(),
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="vector_embeddings",
    )

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "agent_vector_embeddings"
        indexes = [
            models.Index(fields=["user", "vector_id"]),
            models.Index(fields=["created_at"]),
        ]

    def __str__(self):
        return f"VectorEmbedding({self.vector_id})"


class VectorIndex(models.Model):
    """
    Model to track vector index configurations.

    This is useful for managing multiple vector indices with different
    dimensions or distance metrics.
    """

    name = models.CharField(max_length=255, unique=True)
    dimensions = models.IntegerField()
    distance_metric = models.CharField(
        max_length=20,
        choices=[
            ("cosine", "Cosine Distance"),
            ("l2", "Euclidean Distance (L2)"),
            ("inner_product", "Inner Product"),
        ],
        default="cosine",
    )
    description = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "agent_vector_indices"

    def __str__(self):
        return f"VectorIndex({self.name}, dims={self.dimensions})"

