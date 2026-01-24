# Generated migration for RAG support

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('django_agent_runtime', '0008_add_agent_revision'),
    ]

    operations = [
        # Add RAG config to AgentDefinition
        migrations.AddField(
            model_name='agentdefinition',
            name='rag_config',
            field=models.JSONField(
                blank=True,
                default=dict,
                help_text='RAG configuration for this agent: enabled, top_k, similarity_threshold, chunk_size, chunk_overlap, embedding_model',
            ),
        ),
        
        # Add RAG/vector store fields to AgentKnowledge
        migrations.AddField(
            model_name='agentknowledge',
            name='embedding_status',
            field=models.CharField(
                choices=[
                    ('not_indexed', 'Not Indexed'),
                    ('pending', 'Pending'),
                    ('indexing', 'Indexing'),
                    ('indexed', 'Indexed'),
                    ('failed', 'Failed'),
                    ('stale', 'Stale (needs re-indexing)'),
                ],
                default='not_indexed',
                help_text='Status of vector embeddings for RAG',
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name='agentknowledge',
            name='chunk_count',
            field=models.PositiveIntegerField(
                default=0,
                help_text='Number of chunks in vector store',
            ),
        ),
        migrations.AddField(
            model_name='agentknowledge',
            name='content_hash',
            field=models.CharField(
                blank=True,
                help_text='SHA-256 hash of content for change detection',
                max_length=64,
            ),
        ),
        migrations.AddField(
            model_name='agentknowledge',
            name='indexed_at',
            field=models.DateTimeField(
                blank=True,
                help_text='When this knowledge was last indexed',
                null=True,
            ),
        ),
        migrations.AddField(
            model_name='agentknowledge',
            name='embedding_error',
            field=models.TextField(
                blank=True,
                help_text='Error message if embedding failed',
            ),
        ),
        migrations.AddField(
            model_name='agentknowledge',
            name='rag_config',
            field=models.JSONField(
                blank=True,
                default=dict,
                help_text='RAG configuration: chunk_size, chunk_overlap, etc.',
            ),
        ),
    ]

