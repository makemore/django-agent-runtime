"""
Management command to export an agent system to a fixture file.

Usage:
    python manage.py export_agent_system prolo
    python manage.py export_agent_system prolo --output=my_agents.json
    python manage.py export_agent_system prolo --indent=2
    python manage.py export_agent_system prolo --stdout
"""
import json
from django.core.management.base import BaseCommand, CommandError
from django.core.serializers.json import DjangoJSONEncoder


class Command(BaseCommand):
    help = 'Export an agent system (with all agents, tools, versions, knowledge) to a fixture file'

    def add_arguments(self, parser):
        parser.add_argument(
            'system_slug',
            type=str,
            help='Slug of the agent system to export (e.g., "prolo")'
        )
        parser.add_argument(
            '--output', '-o',
            type=str,
            default=None,
            help='Output file path (default: {slug}_agents.json)'
        )
        parser.add_argument(
            '--indent',
            type=int,
            default=2,
            help='JSON indentation level (default: 2)'
        )
        parser.add_argument(
            '--stdout',
            action='store_true',
            help='Output to stdout instead of file'
        )

    def handle(self, *args, **options):
        from django_agent_runtime.models import (
            AgentSystem,
            AgentSystemMember,
            AgentDefinition,
            AgentVersion,
            AgentTool,
            AgentKnowledge,
            DynamicTool,
            SubAgentTool,
        )

        system_slug = options['system_slug']

        # Get the system
        try:
            system = AgentSystem.objects.get(slug=system_slug)
        except AgentSystem.DoesNotExist:
            raise CommandError(f'Agent system "{system_slug}" not found')

        self.stderr.write(f'Exporting agent system: {system.name} ({system.slug})')

        # Collect all related objects
        fixtures = []

        # 1. Get all agents in the system via AgentSystemMember
        members = AgentSystemMember.objects.filter(system=system)
        agent_ids = list(members.values_list('agent_id', flat=True))

        # 2. Get all agent definitions
        agents = AgentDefinition.objects.filter(id__in=agent_ids)
        self.stderr.write(f'  Found {agents.count()} agents')

        # 3. Get all versions for these agents
        versions = AgentVersion.objects.filter(agent__in=agents)
        self.stderr.write(f'  Found {versions.count()} agent versions')

        # 4. Get all tools for these agents
        tools = AgentTool.objects.filter(agent__in=agents)
        self.stderr.write(f'  Found {tools.count()} agent tools')

        # 5. Get all knowledge sources for these agents
        knowledge_sources = AgentKnowledge.objects.filter(agent__in=agents)
        self.stderr.write(f'  Found {knowledge_sources.count()} knowledge sources')

        # 6. Get all dynamic tools for these agents
        dynamic_tools = DynamicTool.objects.filter(agent__in=agents)
        self.stderr.write(f'  Found {dynamic_tools.count()} dynamic tools')

        # 7. Get all sub-agent tools where parent is in our agents
        sub_agent_tools = SubAgentTool.objects.filter(parent_agent__in=agents)
        self.stderr.write(f'  Found {sub_agent_tools.count()} sub-agent tools')

        # Serialize in dependency order (for loaddata compatibility)
        # 1. AgentDefinition first (no dependencies)
        for agent in agents:
            fixtures.append(self._serialize_agent_definition(agent))

        # 2. AgentVersion (depends on AgentDefinition)
        for version in versions:
            fixtures.append(self._serialize_agent_version(version))

        # 3. AgentTool (depends on AgentDefinition, may reference subagent)
        for tool in tools:
            fixtures.append(self._serialize_agent_tool(tool))

        # 4. AgentKnowledge (depends on AgentDefinition)
        for knowledge in knowledge_sources:
            fixtures.append(self._serialize_agent_knowledge(knowledge))

        # 5. DynamicTool (depends on AgentDefinition)
        for dt in dynamic_tools:
            fixtures.append(self._serialize_dynamic_tool(dt))

        # 6. AgentSystem (depends on AgentDefinition for entry_agent)
        fixtures.append(self._serialize_agent_system(system))

        # 7. AgentSystemMember (depends on AgentSystem and AgentDefinition)
        for member in members:
            fixtures.append(self._serialize_agent_system_member(member))

        # 8. SubAgentTool (depends on AgentDefinition for both parent and sub)
        for sat in sub_agent_tools:
            fixtures.append(self._serialize_sub_agent_tool(sat))

        # Output
        json_output = json.dumps(fixtures, indent=options['indent'], cls=DjangoJSONEncoder)

        if options['stdout']:
            self.stdout.write(json_output)
        else:
            output_path = options['output'] or f'{system_slug}_agents.json'
            with open(output_path, 'w') as f:
                f.write(json_output)
            self.stderr.write(self.style.SUCCESS(f'Exported to {output_path}'))
            self.stderr.write(f'  Total objects: {len(fixtures)}')

    def _serialize_agent_definition(self, agent):
        return {
            "model": "django_agent_runtime.agentdefinition",
            "pk": str(agent.id),
            "fields": {
                "slug": agent.slug,
                "name": agent.name,
                "description": agent.description,
                "icon": agent.icon,
                "parent": str(agent.parent_id) if agent.parent_id else None,
                "owner": agent.owner_id,
                "is_public": agent.is_public,
                "is_template": agent.is_template,
                "rag_config": agent.rag_config,
                "file_config": agent.file_config,
                "is_active": agent.is_active,
                "created_at": agent.created_at.isoformat() if agent.created_at else None,
                "updated_at": agent.updated_at.isoformat() if agent.updated_at else None,
            }
        }

    def _serialize_agent_version(self, version):
        return {
            "model": "django_agent_runtime.agentversion",
            "pk": str(version.id),
            "fields": {
                "agent": str(version.agent_id),
                "version": version.version,
                "system_prompt": version.system_prompt,
                "model": version.model,
                "model_settings": version.model_settings,
                "extra_config": version.extra_config,
                "is_active": version.is_active,
                "is_draft": version.is_draft,
                "notes": version.notes,
                "created_at": version.created_at.isoformat() if version.created_at else None,
                "published_at": version.published_at.isoformat() if version.published_at else None,
            }
        }

    def _serialize_agent_tool(self, tool):
        return {
            "model": "django_agent_runtime.agenttool",
            "pk": str(tool.id),
            "fields": {
                "agent": str(tool.agent_id),
                "name": tool.name,
                "tool_type": tool.tool_type,
                "description": tool.description,
                "parameters_schema": tool.parameters_schema,
                "builtin_ref": tool.builtin_ref,
                "subagent": str(tool.subagent_id) if tool.subagent_id else None,
                "invocation_mode": tool.invocation_mode,
                "context_mode": tool.context_mode,
                "max_turns": tool.max_turns,
                "config": tool.config,
                "is_active": tool.is_active,
                "order": tool.order,
            }
        }

    def _serialize_agent_knowledge(self, knowledge):
        return {
            "model": "django_agent_runtime.agentknowledge",
            "pk": str(knowledge.id),
            "fields": {
                "agent": str(knowledge.agent_id),
                "name": knowledge.name,
                "knowledge_type": knowledge.knowledge_type,
                "content": knowledge.content,
                "file": knowledge.file.name if knowledge.file else "",
                "url": knowledge.url,
                "dynamic_config": knowledge.dynamic_config,
                "inclusion_mode": knowledge.inclusion_mode,
                "embedding_status": knowledge.embedding_status,
                "chunk_count": knowledge.chunk_count,
                "content_hash": knowledge.content_hash,
                "indexed_at": knowledge.indexed_at.isoformat() if knowledge.indexed_at else None,
                "embedding_error": knowledge.embedding_error,
                "rag_config": knowledge.rag_config,
                "is_active": knowledge.is_active,
                "order": knowledge.order,
                "created_at": knowledge.created_at.isoformat() if knowledge.created_at else None,
                "updated_at": knowledge.updated_at.isoformat() if knowledge.updated_at else None,
            }
        }

    def _serialize_dynamic_tool(self, dt):
        return {
            "model": "django_agent_runtime.dynamictool",
            "pk": str(dt.id),
            "fields": {
                "agent": str(dt.agent_id),
                "name": dt.name,
                "description": dt.description,
                "function_path": dt.function_path,
                "source_file": dt.source_file,
                "source_line": dt.source_line,
                "parameters_schema": dt.parameters_schema,
                "execution_mode": dt.execution_mode,
                "timeout_seconds": dt.timeout_seconds,
                "is_safe": dt.is_safe,
                "requires_confirmation": dt.requires_confirmation,
                "allowed_for_auto_execution": dt.allowed_for_auto_execution,
                "allowed_imports": dt.allowed_imports,
                "blocked_imports": dt.blocked_imports,
                "is_active": dt.is_active,
                "is_verified": dt.is_verified,
                "version": dt.version,
                "created_at": dt.created_at.isoformat() if dt.created_at else None,
                "updated_at": dt.updated_at.isoformat() if dt.updated_at else None,
                "created_by": dt.created_by_id,
                "discovered_function": str(dt.discovered_function_id) if dt.discovered_function_id else None,
            }
        }

    def _serialize_agent_system(self, system):
        return {
            "model": "django_agent_runtime.agentsystem",
            "pk": str(system.id),
            "fields": {
                "slug": system.slug,
                "name": system.name,
                "description": system.description,
                "shared_knowledge": system.shared_knowledge,
                "entry_agent": str(system.entry_agent_id) if system.entry_agent_id else None,
                "owner": system.owner_id,
                "is_active": system.is_active,
                "created_at": system.created_at.isoformat() if system.created_at else None,
                "updated_at": system.updated_at.isoformat() if system.updated_at else None,
            }
        }

    def _serialize_agent_system_member(self, member):
        return {
            "model": "django_agent_runtime.agentsystemmember",
            "pk": str(member.id),
            "fields": {
                "system": str(member.system_id),
                "agent": str(member.agent_id),
                "role": member.role,
                "notes": member.notes,
                "order": member.order,
            }
        }

    def _serialize_sub_agent_tool(self, sat):
        return {
            "model": "django_agent_runtime.subagenttool",
            "pk": str(sat.id),
            "fields": {
                "parent_agent": str(sat.parent_agent_id),
                "sub_agent": str(sat.sub_agent_id),
                "name": sat.name,
                "description": sat.description,
                "context_mode": sat.context_mode,
                "is_active": sat.is_active,
                "created_at": sat.created_at.isoformat() if sat.created_at else None,
                "updated_at": sat.updated_at.isoformat() if sat.updated_at else None,
            }
        }

