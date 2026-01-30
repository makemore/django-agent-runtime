# Generated migration for task list feature

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import uuid


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("django_agent_runtime", "0023_add_superseded_by"),
    ]

    operations = [
        migrations.CreateModel(
            name="AgentTaskList",
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
                    "name",
                    models.CharField(
                        default="Current Task List",
                        help_text="Name of the task list",
                        max_length=255,
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("metadata", models.JSONField(blank=True, default=dict)),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="agent_task_lists",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "conversation",
                    models.ForeignKey(
                        blank=True,
                        help_text="Optional conversation this task list is associated with",
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="task_lists",
                        to="django_agent_runtime.agentconversation",
                    ),
                ),
            ],
            options={
                "verbose_name": "Agent Task List",
                "verbose_name_plural": "Agent Task Lists",
                "db_table": "agent_runtime_task_list",
                "ordering": ["-updated_at"],
                "abstract": False,
            },
        ),
        migrations.CreateModel(
            name="AgentTask",
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
                    "name",
                    models.CharField(
                        help_text="Short name/title of the task",
                        max_length=500,
                    ),
                ),
                (
                    "description",
                    models.TextField(
                        blank=True,
                        default="",
                        help_text="Detailed description of the task",
                    ),
                ),
                (
                    "state",
                    models.CharField(
                        choices=[
                            ("not_started", "Not Started"),
                            ("in_progress", "In Progress"),
                            ("complete", "Complete"),
                            ("cancelled", "Cancelled"),
                        ],
                        db_index=True,
                        default="not_started",
                        max_length=20,
                    ),
                ),
                (
                    "order",
                    models.PositiveIntegerField(
                        default=0,
                        help_text="Order within the task list or parent task",
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "completed_at",
                    models.DateTimeField(
                        blank=True,
                        help_text="When the task was marked complete",
                        null=True,
                    ),
                ),
                ("metadata", models.JSONField(blank=True, default=dict)),
                (
                    "parent",
                    models.ForeignKey(
                        blank=True,
                        help_text="Parent task (for nested tasks)",
                        null=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="subtasks",
                        to="django_agent_runtime.agenttask",
                    ),
                ),
                (
                    "task_list",
                    models.ForeignKey(
                        help_text="The task list this task belongs to",
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="tasks",
                        to="django_agent_runtime.agenttasklist",
                    ),
                ),
            ],
            options={
                "verbose_name": "Agent Task",
                "verbose_name_plural": "Agent Tasks",
                "db_table": "agent_runtime_task",
                "ordering": ["order", "created_at"],
                "abstract": False,
            },
        ),
    ]

