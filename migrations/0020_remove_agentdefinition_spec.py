"""
Remove the spec field from AgentDefinition model.

This field has been replaced by the SpecDocument system which provides:
- Version history
- Hierarchical document structure
- Better organization for multi-agent systems
"""

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('django_agent_runtime', '0019_migrate_spec_to_documents'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='agentdefinition',
            name='spec',
        ),
    ]

