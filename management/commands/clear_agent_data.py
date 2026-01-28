"""
Management command to clear all agent data from Django models.

Usage:
    ./manage.py clear_agent_data
    ./manage.py clear_agent_data --keep-definitions  # Keep agent definitions, clear runtime data
    ./manage.py clear_agent_data --only-runs         # Only clear runs, events, conversations
    ./manage.py clear_agent_data --yes               # Skip confirmation prompt
"""

from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Clear all agent data from Django models"

    def add_arguments(self, parser):
        parser.add_argument(
            "--keep-definitions",
            action="store_true",
            help="Keep agent definitions (AgentDefinition, AgentVersion, etc.) but clear runtime data",
        )
        parser.add_argument(
            "--only-runs",
            action="store_true",
            help="Only clear runs, events, and conversations (minimal cleanup)",
        )
        parser.add_argument(
            "--yes", "-y",
            action="store_true",
            help="Skip confirmation prompt",
        )

    def handle(self, *args, **options):
        from django_agent_runtime.models import (
            # Runtime models
            AgentConversation,
            AgentRun,
            AgentEvent,
            AgentCheckpoint,
            AgentFile,
            # Persistence models
            Memory,
            PersistenceConversation,
            PersistenceMessage,
            PersistenceTaskList,
            PersistenceTask,
            Preferences,
            # Agent Definition models
            AgentDefinition,
            AgentVersion,
            AgentRevision,
            AgentTool,
            AgentKnowledge,
            # Dynamic Tool models
            DiscoveredFunction,
            DynamicTool,
            DynamicToolExecution,
            # Sub-agent tool model
            SubAgentTool,
            # Multi-agent system models
            AgentSystem,
            AgentSystemMember,
            AgentSystemVersion,
            AgentSystemSnapshot,
            # Spec document models
            SpecDocument,
            SpecDocumentVersion,
            # Step execution models
            StepCheckpoint,
            StepEvent,
        )

        keep_definitions = options["keep_definitions"]
        only_runs = options["only_runs"]
        skip_confirm = options["yes"]

        # Build list of models to clear based on options
        if only_runs:
            models_to_clear = [
                ("AgentEvent", AgentEvent),
                ("AgentRun", AgentRun),
                ("AgentConversation", AgentConversation),
            ]
        elif keep_definitions:
            models_to_clear = [
                # Runtime models
                ("AgentEvent", AgentEvent),
                ("AgentRun", AgentRun),
                ("AgentConversation", AgentConversation),
                ("AgentCheckpoint", AgentCheckpoint),
                ("AgentFile", AgentFile),
                # Persistence models
                ("Memory", Memory),
                ("PersistenceMessage", PersistenceMessage),
                ("PersistenceTask", PersistenceTask),
                ("PersistenceTaskList", PersistenceTaskList),
                ("PersistenceConversation", PersistenceConversation),
                ("Preferences", Preferences),
                # Step execution models
                ("StepEvent", StepEvent),
                ("StepCheckpoint", StepCheckpoint),
                # Dynamic tool executions (but keep tool definitions)
                ("DynamicToolExecution", DynamicToolExecution),
            ]
        else:
            # Clear everything
            models_to_clear = [
                # Runtime models (order matters for FK constraints)
                ("AgentEvent", AgentEvent),
                ("AgentRun", AgentRun),
                ("AgentConversation", AgentConversation),
                ("AgentCheckpoint", AgentCheckpoint),
                ("AgentFile", AgentFile),
                # Persistence models
                ("Memory", Memory),
                ("PersistenceMessage", PersistenceMessage),
                ("PersistenceTask", PersistenceTask),
                ("PersistenceTaskList", PersistenceTaskList),
                ("PersistenceConversation", PersistenceConversation),
                ("Preferences", Preferences),
                # Step execution models
                ("StepEvent", StepEvent),
                ("StepCheckpoint", StepCheckpoint),
                # Dynamic tool models
                ("DynamicToolExecution", DynamicToolExecution),
                ("DynamicTool", DynamicTool),
                ("DiscoveredFunction", DiscoveredFunction),
                # Spec document models
                ("SpecDocumentVersion", SpecDocumentVersion),
                ("SpecDocument", SpecDocument),
                # Multi-agent system models
                ("AgentSystemSnapshot", AgentSystemSnapshot),
                ("AgentSystemVersion", AgentSystemVersion),
                ("AgentSystemMember", AgentSystemMember),
                ("AgentSystem", AgentSystem),
                # Agent definition models (order matters for FK constraints)
                ("SubAgentTool", SubAgentTool),
                ("AgentKnowledge", AgentKnowledge),
                ("AgentTool", AgentTool),
                ("AgentRevision", AgentRevision),
                ("AgentVersion", AgentVersion),
                ("AgentDefinition", AgentDefinition),
            ]

        # Show what will be deleted
        self.stdout.write("\nThe following data will be deleted:")
        total_count = 0
        for name, model in models_to_clear:
            count = model.objects.count()
            total_count += count
            if count > 0:
                self.stdout.write(f"  - {name}: {count} records")

        if total_count == 0:
            self.stdout.write(self.style.SUCCESS("\nNo data to clear."))
            return

        self.stdout.write(f"\nTotal: {total_count} records")

        # Confirm
        if not skip_confirm:
            confirm = input("\nAre you sure you want to delete this data? [y/N] ")
            if confirm.lower() != "y":
                self.stdout.write(self.style.WARNING("Aborted."))
                return

        # Delete in order
        self.stdout.write("\nDeleting...")
        for name, model in models_to_clear:
            count, _ = model.objects.all().delete()
            if count > 0:
                self.stdout.write(f"  Deleted {count} {name} records")

        self.stdout.write(self.style.SUCCESS("\nAll agent data cleared successfully."))

