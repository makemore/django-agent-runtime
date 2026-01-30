# Generated migration for collaborator models

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import uuid


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("django_agent_runtime", "0024_add_task_list"),
    ]

    operations = [
        migrations.CreateModel(
            name="AgentCollaborator",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                (
                    "role",
                    models.CharField(
                        choices=[
                            ("viewer", "Viewer"),
                            ("editor", "Editor"),
                            ("admin", "Admin"),
                        ],
                        default="viewer",
                        help_text="The level of access granted to this user",
                        max_length=20,
                    ),
                ),
                ("added_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "agent",
                    models.ForeignKey(
                        help_text="The agent this collaborator has access to",
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="collaborators",
                        to="django_agent_runtime.agentdefinition",
                    ),
                ),
                (
                    "user",
                    models.ForeignKey(
                        help_text="The user who has been granted access",
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="agent_collaborations",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "added_by",
                    models.ForeignKey(
                        blank=True,
                        help_text="The user who added this collaborator",
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="agent_collaborators_added",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "verbose_name": "Agent Collaborator",
                "verbose_name_plural": "Agent Collaborators",
                "ordering": ["role", "user__email"],
                "unique_together": {("agent", "user")},
            },
        ),
        migrations.CreateModel(
            name="SystemCollaborator",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                (
                    "role",
                    models.CharField(
                        choices=[
                            ("viewer", "Viewer"),
                            ("editor", "Editor"),
                            ("admin", "Admin"),
                        ],
                        default="viewer",
                        help_text="The level of access granted to this user",
                        max_length=20,
                    ),
                ),
                ("added_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "system",
                    models.ForeignKey(
                        help_text="The system this collaborator has access to",
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="collaborators",
                        to="django_agent_runtime.agentsystem",
                    ),
                ),
                (
                    "user",
                    models.ForeignKey(
                        help_text="The user who has been granted access",
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="system_collaborations",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "added_by",
                    models.ForeignKey(
                        blank=True,
                        help_text="The user who added this collaborator",
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="system_collaborators_added",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "verbose_name": "System Collaborator",
                "verbose_name_plural": "System Collaborators",
                "ordering": ["role", "user__email"],
                "unique_together": {("system", "user")},
            },
        ),
    ]

