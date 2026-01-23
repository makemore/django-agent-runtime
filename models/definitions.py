"""
Agent Definition models for storing configurable agent configurations.

These models allow agents to be defined and configured via the database,
enabling dynamic agent creation without code changes.
"""

import uuid
from django.db import models
from django.conf import settings


class AgentDefinition(models.Model):
    """
    A configurable agent definition stored in the database.
    
    This is the "template" for an agent - it defines the system prompt,
    model settings, available tools, and knowledge sources.
    
    Agents can inherit from other agents (parent), allowing for
    template-based customization.
    """
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    
    # Unique identifier used as agent_key in the runtime
    slug = models.SlugField(
        max_length=100,
        unique=True,
        help_text="Unique identifier for this agent (used as agent_key)",
    )
    
    # Human-readable name
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    
    # Optional icon/avatar
    icon = models.CharField(
        max_length=100,
        blank=True,
        help_text="Icon identifier (emoji or icon class)",
    )
    
    # Inheritance - allows agents to extend other agents
    parent = models.ForeignKey(
        'self',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='children',
        help_text="Parent agent to inherit configuration from",
    )
    
    # Owner (optional - for multi-tenant scenarios)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='agent_definitions',
    )
    
    # Visibility
    is_public = models.BooleanField(
        default=False,
        help_text="Whether this agent is publicly accessible",
    )
    is_template = models.BooleanField(
        default=False,
        help_text="Whether this agent can be used as a template for others",
    )
    
    # Status
    is_active = models.BooleanField(default=True)
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['-updated_at']
        verbose_name = "Agent Definition"
        verbose_name_plural = "Agent Definitions"
    
    def __str__(self):
        return f"{self.name} ({self.slug})"
    
    def get_effective_config(self) -> dict:
        """
        Get the effective configuration, merging parent configs.
        
        Returns the fully resolved configuration including inherited values.
        """
        # Start with parent config if exists
        if self.parent:
            config = self.parent.get_effective_config()
        else:
            config = {
                'system_prompt': '',
                'model': 'gpt-4o',
                'model_settings': {},
                'tools': [],
                'knowledge': [],
            }
        
        # Get the active version's config
        active_version = self.versions.filter(is_active=True).first()
        if active_version:
            # Merge version config (child overrides parent)
            if active_version.system_prompt:
                config['system_prompt'] = active_version.system_prompt
            if active_version.model:
                config['model'] = active_version.model
            if active_version.model_settings:
                config['model_settings'] = {
                    **config.get('model_settings', {}),
                    **active_version.model_settings,
                }
            if active_version.extra_config:
                config['extra'] = {
                    **config.get('extra', {}),
                    **active_version.extra_config,
                }
        
        # Add tools from this agent
        for tool in self.tools.filter(is_active=True):
            config['tools'].append(tool.to_schema())
        
        # Add knowledge from this agent
        for knowledge in self.knowledge_sources.filter(is_active=True):
            config['knowledge'].append(knowledge.to_dict())

        return config


class AgentVersion(models.Model):
    """
    A version of an agent's configuration.

    Allows tracking changes to agent configuration over time,
    with the ability to rollback to previous versions.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    agent = models.ForeignKey(
        AgentDefinition,
        on_delete=models.CASCADE,
        related_name='versions',
    )

    # Version identifier
    version = models.CharField(
        max_length=50,
        help_text="Version string (e.g., '1.0.0', 'draft')",
    )

    # Core configuration
    system_prompt = models.TextField(
        blank=True,
        help_text="The system prompt for this agent",
    )

    # Model configuration
    model = models.CharField(
        max_length=100,
        default='gpt-4o',
        help_text="LLM model to use (e.g., 'gpt-4o', 'claude-3-opus')",
    )
    model_settings = models.JSONField(
        default=dict,
        blank=True,
        help_text="Model-specific settings (temperature, max_tokens, etc.)",
    )

    # Additional configuration
    extra_config = models.JSONField(
        default=dict,
        blank=True,
        help_text="Additional configuration options",
    )

    # Status
    is_active = models.BooleanField(
        default=False,
        help_text="Whether this is the active version",
    )
    is_draft = models.BooleanField(
        default=True,
        help_text="Whether this version is still being edited",
    )

    # Metadata
    notes = models.TextField(
        blank=True,
        help_text="Release notes or change description",
    )

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    published_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']
        unique_together = [('agent', 'version')]
        verbose_name = "Agent Version"
        verbose_name_plural = "Agent Versions"

    def __str__(self):
        status = "active" if self.is_active else ("draft" if self.is_draft else "archived")
        return f"{self.agent.name} v{self.version} ({status})"

    def save(self, *args, **kwargs):
        # Ensure only one active version per agent
        if self.is_active:
            AgentVersion.objects.filter(
                agent=self.agent,
                is_active=True,
            ).exclude(pk=self.pk).update(is_active=False)
        super().save(*args, **kwargs)


class AgentTool(models.Model):
    """
    A tool available to an agent.

    Tools can be:
    - Built-in tools (referenced by name)
    - Custom function tools (with schema)
    - Sub-agent tools (delegate to another agent)
    """

    class ToolType(models.TextChoices):
        BUILTIN = 'builtin', 'Built-in Tool'
        FUNCTION = 'function', 'Custom Function'
        SUBAGENT = 'subagent', 'Sub-Agent'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    agent = models.ForeignKey(
        AgentDefinition,
        on_delete=models.CASCADE,
        related_name='tools',
    )

    # Tool identification
    name = models.CharField(
        max_length=100,
        help_text="Tool name (must be unique within agent)",
    )
    tool_type = models.CharField(
        max_length=20,
        choices=ToolType.choices,
        default=ToolType.FUNCTION,
    )

    # Tool description (for LLM)
    description = models.TextField(
        help_text="Description of what the tool does (shown to LLM)",
    )

    # For FUNCTION type: JSON Schema for parameters
    parameters_schema = models.JSONField(
        default=dict,
        blank=True,
        help_text="JSON Schema for tool parameters",
    )

    # For BUILTIN type: reference to built-in tool
    builtin_ref = models.CharField(
        max_length=100,
        blank=True,
        help_text="Reference to built-in tool (e.g., 'web_search')",
    )

    # For SUBAGENT type: reference to another agent
    subagent = models.ForeignKey(
        AgentDefinition,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='used_as_tool_in',
        help_text="Agent to delegate to (for subagent tools)",
    )

    # Configuration
    config = models.JSONField(
        default=dict,
        blank=True,
        help_text="Additional tool configuration",
    )

    # Status
    is_active = models.BooleanField(default=True)

    # Ordering
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['order', 'name']
        unique_together = [('agent', 'name')]
        verbose_name = "Agent Tool"
        verbose_name_plural = "Agent Tools"

    def __str__(self):
        return f"{self.agent.name} - {self.name}"

    def to_schema(self) -> dict:
        """Convert to OpenAI function schema format."""
        return {
            'type': 'function',
            'function': {
                'name': self.name,
                'description': self.description,
                'parameters': self.parameters_schema or {
                    'type': 'object',
                    'properties': {},
                },
            },
            '_meta': {
                'tool_type': self.tool_type,
                'builtin_ref': self.builtin_ref,
                'subagent_id': str(self.subagent_id) if self.subagent_id else None,
                'config': self.config,
            },
        }


class AgentKnowledge(models.Model):
    """
    Knowledge source for an agent.

    Knowledge can be:
    - Static text (instructions, context)
    - File references (documents to include)
    - Dynamic sources (API endpoints, database queries)
    """

    class KnowledgeType(models.TextChoices):
        TEXT = 'text', 'Static Text'
        FILE = 'file', 'File/Document'
        URL = 'url', 'URL/Webpage'
        DYNAMIC = 'dynamic', 'Dynamic Source'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    agent = models.ForeignKey(
        AgentDefinition,
        on_delete=models.CASCADE,
        related_name='knowledge_sources',
    )

    # Knowledge identification
    name = models.CharField(
        max_length=255,
        help_text="Name/title of this knowledge source",
    )
    knowledge_type = models.CharField(
        max_length=20,
        choices=KnowledgeType.choices,
        default=KnowledgeType.TEXT,
    )

    # For TEXT type: the actual content
    content = models.TextField(
        blank=True,
        help_text="Text content (for text type)",
    )

    # For FILE type: file reference
    file = models.FileField(
        upload_to='agent_knowledge/',
        blank=True,
        null=True,
        help_text="Uploaded file (for file type)",
    )

    # For URL type: URL to fetch
    url = models.URLField(
        blank=True,
        help_text="URL to fetch content from (for url type)",
    )

    # For DYNAMIC type: configuration
    dynamic_config = models.JSONField(
        default=dict,
        blank=True,
        help_text="Configuration for dynamic knowledge source",
    )

    # How to include this knowledge
    inclusion_mode = models.CharField(
        max_length=20,
        choices=[
            ('always', 'Always Include'),
            ('on_demand', 'On Demand (via tool)'),
            ('rag', 'RAG (similarity search)'),
        ],
        default='always',
    )

    # Status
    is_active = models.BooleanField(default=True)

    # Ordering
    order = models.PositiveIntegerField(default=0)

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['order', 'name']
        verbose_name = "Agent Knowledge"
        verbose_name_plural = "Agent Knowledge Sources"

    def __str__(self):
        return f"{self.agent.name} - {self.name}"

    def to_dict(self) -> dict:
        """Convert to dictionary for configuration."""
        return {
            'id': str(self.id),
            'name': self.name,
            'type': self.knowledge_type,
            'inclusion_mode': self.inclusion_mode,
            'content': self.content if self.knowledge_type == 'text' else None,
            'file': self.file.url if self.file else None,
            'url': self.url if self.knowledge_type == 'url' else None,
            'dynamic_config': self.dynamic_config if self.knowledge_type == 'dynamic' else None,
        }

