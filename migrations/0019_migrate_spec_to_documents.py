"""
Data migration to move AgentDefinition.spec field data to SpecDocument records.

For each agent that has a non-empty spec field:
1. Check if a SpecDocument is already linked to this agent
2. If not, create a new SpecDocument with the agent's spec content
3. Link the document to the agent
"""

from django.db import migrations


def migrate_specs_to_documents(apps, schema_editor):
    """Move spec data from AgentDefinition to SpecDocument."""
    AgentDefinition = apps.get_model('django_agent_runtime', 'AgentDefinition')
    SpecDocument = apps.get_model('django_agent_runtime', 'SpecDocument')
    SpecDocumentVersion = apps.get_model('django_agent_runtime', 'SpecDocumentVersion')
    
    for agent in AgentDefinition.objects.all():
        # Skip agents without specs
        if not agent.spec or not agent.spec.strip():
            continue
        
        # Check if agent already has a linked spec document
        existing_doc = SpecDocument.objects.filter(linked_agent=agent).first()
        if existing_doc:
            # Update existing document if content differs
            if existing_doc.content != agent.spec:
                existing_doc.content = agent.spec
                existing_doc.current_version += 1
                existing_doc.save()
                # Create version record
                SpecDocumentVersion.objects.create(
                    document=existing_doc,
                    version_number=existing_doc.current_version,
                    title=existing_doc.title,
                    content=existing_doc.content,
                    change_summary="Migrated from agent spec field",
                )
            continue
        
        # Create new spec document for this agent
        doc = SpecDocument.objects.create(
            title=f"{agent.name} Specification",
            content=agent.spec,
            linked_agent=agent,
            owner=agent.owner,
            current_version=1,
        )
        
        # Create initial version record
        SpecDocumentVersion.objects.create(
            document=doc,
            version_number=1,
            title=doc.title,
            content=doc.content,
            change_summary="Initial migration from agent spec field",
        )
        
        print(f"  Migrated spec for agent: {agent.name} ({agent.slug})")


def reverse_migration(apps, schema_editor):
    """Reverse: Copy SpecDocument content back to agent.spec field."""
    AgentDefinition = apps.get_model('django_agent_runtime', 'AgentDefinition')
    SpecDocument = apps.get_model('django_agent_runtime', 'SpecDocument')
    
    for doc in SpecDocument.objects.filter(linked_agent__isnull=False):
        agent = doc.linked_agent
        agent.spec = doc.content
        agent.save(update_fields=['spec'])
        print(f"  Restored spec for agent: {agent.name}")


class Migration(migrations.Migration):

    dependencies = [
        ('django_agent_runtime', '0018_add_file_config'),
    ]

    operations = [
        migrations.RunPython(
            migrate_specs_to_documents,
            reverse_code=reverse_migration,
        ),
    ]

