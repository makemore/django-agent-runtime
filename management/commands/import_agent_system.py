"""
Management command to import an agent system from a fixture file.

Wraps Django's loaddata with validation and options for handling
user references and UUID conflicts.

Usage:
    python manage.py import_agent_system my_agents.json
    python manage.py import_agent_system my_agents.json --dry-run
    python manage.py import_agent_system my_agents.json --clear-owners
    python manage.py import_agent_system my_agents.json --assign-owner=admin
    python manage.py import_agent_system my_agents.json --new-uuids
"""
import json
import uuid
from django.core.management.base import BaseCommand, CommandError
from django.contrib.auth import get_user_model


class Command(BaseCommand):
    help = 'Import an agent system from a fixture file with validation and options'

    def add_arguments(self, parser):
        parser.add_argument(
            'fixture_file',
            type=str,
            help='Path to the fixture JSON file to import'
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Validate and show what would be imported without making changes'
        )
        parser.add_argument(
            '--clear-owners',
            action='store_true',
            help='Set all owner/created_by fields to NULL'
        )
        parser.add_argument(
            '--assign-owner',
            type=str,
            default=None,
            help='Assign all objects to this user (username)'
        )
        parser.add_argument(
            '--new-uuids',
            action='store_true',
            help='Generate new UUIDs for all objects (creates copies instead of overwriting)'
        )
        parser.add_argument(
            '--skip-existing',
            action='store_true',
            help='Skip objects that already exist (by slug for agents/systems)'
        )

    def handle(self, *args, **options):
        fixture_file = options['fixture_file']
        dry_run = options['dry_run']
        clear_owners = options['clear_owners']
        assign_owner = options['assign_owner']
        new_uuids = options['new_uuids']
        skip_existing = options['skip_existing']

        # Load and parse fixture
        try:
            with open(fixture_file, 'r') as f:
                fixtures = json.load(f)
        except FileNotFoundError:
            raise CommandError(f'Fixture file not found: {fixture_file}')
        except json.JSONDecodeError as e:
            raise CommandError(f'Invalid JSON in fixture file: {e}')

        if not isinstance(fixtures, list):
            raise CommandError('Fixture must be a JSON array')

        self.stderr.write(f'Loaded {len(fixtures)} objects from {fixture_file}')

        # Validate and categorize objects
        stats = self._categorize_fixtures(fixtures)
        self._print_stats(stats)

        # Resolve owner if specified
        owner_id = None
        if assign_owner:
            User = get_user_model()
            try:
                user = User.objects.get(username=assign_owner)
                owner_id = user.id
                self.stderr.write(f'Will assign owner: {user.username} (ID: {owner_id})')
            except User.DoesNotExist:
                raise CommandError(f'User not found: {assign_owner}')

        # Check for conflicts
        conflicts = self._check_conflicts(fixtures, skip_existing)
        if conflicts and not skip_existing:
            self.stderr.write(self.style.WARNING(f'Found {len(conflicts)} potential conflicts:'))
            for conflict in conflicts[:10]:  # Show first 10
                self.stderr.write(f'  - {conflict}')
            if len(conflicts) > 10:
                self.stderr.write(f'  ... and {len(conflicts) - 10} more')
            if not new_uuids:
                self.stderr.write(self.style.WARNING(
                    'Use --new-uuids to create copies or --skip-existing to skip conflicts'
                ))

        if dry_run:
            self.stderr.write(self.style.SUCCESS('Dry run complete. No changes made.'))
            return

        # Transform fixtures based on options
        uuid_map = {}  # old_uuid -> new_uuid mapping
        transformed = self._transform_fixtures(
            fixtures,
            clear_owners=clear_owners,
            owner_id=owner_id,
            new_uuids=new_uuids,
            skip_existing=skip_existing,
            uuid_map=uuid_map,
        )

        if not transformed:
            self.stderr.write(self.style.WARNING('No objects to import after filtering.'))
            return

        self.stderr.write(f'Importing {len(transformed)} objects...')

        # Write to temp file and use loaddata
        import tempfile
        import os
        from django.core.management import call_command

        with tempfile.NamedTemporaryFile(
            mode='w',
            suffix='.json',
            delete=False
        ) as tmp:
            json.dump(transformed, tmp)
            tmp_path = tmp.name

        try:
            call_command('loaddata', tmp_path, verbosity=0)
            self.stderr.write(self.style.SUCCESS(f'Successfully imported {len(transformed)} objects'))
        except Exception as e:
            raise CommandError(f'Import failed: {e}')
        finally:
            os.unlink(tmp_path)

        # Print UUID mapping if new UUIDs were generated
        if new_uuids and uuid_map:
            self.stderr.write('\nUUID mapping (old -> new):')
            for old, new in list(uuid_map.items())[:10]:
                self.stderr.write(f'  {old} -> {new}')
            if len(uuid_map) > 10:
                self.stderr.write(f'  ... and {len(uuid_map) - 10} more')

    def _categorize_fixtures(self, fixtures):
        """Categorize fixtures by model type and return stats."""
        stats = {}
        for obj in fixtures:
            model = obj.get('model', 'unknown')
            stats[model] = stats.get(model, 0) + 1
        return stats

    def _print_stats(self, stats):
        """Print fixture statistics."""
        self.stderr.write('Objects by type:')
        for model, count in sorted(stats.items()):
            short_name = model.split('.')[-1] if '.' in model else model
            self.stderr.write(f'  {short_name}: {count}')

    def _check_conflicts(self, fixtures, skip_existing):
        """Check for existing objects that would conflict."""
        from django_agent_runtime.models import AgentDefinition, AgentSystem

        conflicts = []

        for obj in fixtures:
            model = obj.get('model', '')
            fields = obj.get('fields', {})
            pk = obj.get('pk')

            if model == 'django_agent_runtime.agentdefinition':
                slug = fields.get('slug')
                if slug and AgentDefinition.objects.filter(slug=slug).exists():
                    conflicts.append(f'AgentDefinition with slug "{slug}" already exists')
                elif pk and AgentDefinition.objects.filter(id=pk).exists():
                    conflicts.append(f'AgentDefinition with ID {pk} already exists')

            elif model == 'django_agent_runtime.agentsystem':
                slug = fields.get('slug')
                if slug and AgentSystem.objects.filter(slug=slug).exists():
                    conflicts.append(f'AgentSystem with slug "{slug}" already exists')
                elif pk and AgentSystem.objects.filter(id=pk).exists():
                    conflicts.append(f'AgentSystem with ID {pk} already exists')

        return conflicts

    def _transform_fixtures(self, fixtures, clear_owners, owner_id, new_uuids,
                           skip_existing, uuid_map):
        """Transform fixtures based on options."""
        from django_agent_runtime.models import AgentDefinition, AgentSystem

        # Models that have owner/created_by fields
        owner_fields = {
            'django_agent_runtime.agentdefinition': ['owner'],
            'django_agent_runtime.agentsystem': ['owner'],
            'django_agent_runtime.dynamictool': ['created_by'],
        }

        # FK fields that reference UUIDs (need remapping if new_uuids)
        uuid_fk_fields = {
            'django_agent_runtime.agentdefinition': ['parent'],
            'django_agent_runtime.agentversion': ['agent'],
            'django_agent_runtime.agenttool': ['agent', 'subagent'],
            'django_agent_runtime.agentknowledge': ['agent'],
            'django_agent_runtime.dynamictool': ['agent', 'discovered_function'],
            'django_agent_runtime.agentsystem': ['entry_agent'],
            'django_agent_runtime.agentsystemmember': ['system', 'agent'],
            'django_agent_runtime.subagenttool': ['parent_agent', 'sub_agent'],
        }

        # First pass: generate new UUIDs if needed
        if new_uuids:
            for obj in fixtures:
                old_pk = obj.get('pk')
                if old_pk:
                    uuid_map[old_pk] = str(uuid.uuid4())

        transformed = []
        existing_slugs = set()

        # Get existing slugs if skip_existing
        if skip_existing:
            existing_slugs.update(
                AgentDefinition.objects.values_list('slug', flat=True)
            )
            existing_slugs.update(
                AgentSystem.objects.values_list('slug', flat=True)
            )

        for obj in fixtures:
            model = obj.get('model', '')
            fields = obj.get('fields', {}).copy()
            pk = obj.get('pk')

            # Skip existing if requested
            if skip_existing:
                slug = fields.get('slug')
                if slug and slug in existing_slugs:
                    self.stderr.write(f'  Skipping existing: {slug}')
                    continue

            # Handle owner fields
            if model in owner_fields:
                for field in owner_fields[model]:
                    if field in fields:
                        if clear_owners:
                            fields[field] = None
                        elif owner_id is not None:
                            fields[field] = owner_id

            # Remap UUIDs if new_uuids
            if new_uuids:
                # Remap primary key
                if pk and pk in uuid_map:
                    pk = uuid_map[pk]

                # Remap FK fields
                if model in uuid_fk_fields:
                    for field in uuid_fk_fields[model]:
                        if field in fields and fields[field]:
                            old_ref = fields[field]
                            if old_ref in uuid_map:
                                fields[field] = uuid_map[old_ref]

            transformed.append({
                'model': model,
                'pk': pk,
                'fields': fields,
            })

        return transformed

