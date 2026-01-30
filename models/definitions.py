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

    # Note: Agent specifications are now stored in SpecDocument model
    # which provides version history and hierarchical organization.
    # Use agent.spec_documents.first() to get the linked spec document.

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

    # ==========================================================================
    # RAG / Vector Store Configuration
    # ==========================================================================

    rag_config = models.JSONField(
        default=dict,
        blank=True,
        help_text="""RAG configuration for this agent. Example:
        {
            "enabled": true,
            "top_k": 5,
            "similarity_threshold": 0.7,
            "chunk_size": 500,
            "chunk_overlap": 50,
            "embedding_model": "text-embedding-3-small"
        }""",
    )

    # ==========================================================================
    # File Upload / Processing Configuration
    # ==========================================================================

    file_config = models.JSONField(
        default=dict,
        blank=True,
        help_text="""File upload and processing configuration for this agent. Example:
        {
            "enabled": true,
            "max_file_size_mb": 100,
            "allowed_types": ["image/*", "application/pdf", "text/*"],
            "ocr_provider": "tesseract",
            "vision_provider": "openai",
            "enable_thumbnails": true,
            "storage_path": "agent_files/{agent_id}/"
        }

        Supported OCR providers: tesseract, google_vision, aws_textract, azure_di
        Supported vision providers: openai, anthropic, gemini
        """,
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
                'rag_config': {
                    'enabled': False,
                    'top_k': 5,
                    'similarity_threshold': 0.7,
                    'chunk_size': 500,
                    'chunk_overlap': 50,
                },
                'spec': '',
            }

        # Add spec from linked SpecDocument (child overrides parent)
        spec_doc = self.spec_documents.first()
        if spec_doc:
            config['spec'] = spec_doc.content

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

        # Merge RAG config from this agent
        if self.rag_config:
            config['rag_config'] = {
                **config.get('rag_config', {}),
                **self.rag_config,
            }

        # Add tools from this agent
        for tool in self.tools.filter(is_active=True):
            config['tools'].append(tool.to_schema())

        # Add knowledge from this agent
        for knowledge in self.knowledge_sources.filter(is_active=True):
            config['knowledge'].append(knowledge.to_dict())

        # Add sub-agent tools from this agent
        config['sub_agent_tools'] = []
        for sub_tool in self.sub_agent_tools.filter(is_active=True).select_related('sub_agent'):
            config['sub_agent_tools'].append(sub_tool.to_config_dict())

        return config

    def to_config_dict(self) -> dict:
        """
        Export the agent configuration in the portable AgentConfig format.

        This format can be:
        - Stored as a JSON revision
        - Loaded by JsonAgentRuntime
        - Used in standalone Python scripts

        Returns:
            Dictionary in AgentConfig schema format
        """
        from datetime import datetime

        # Get active version
        active_version = self.versions.filter(is_active=True).first()

        # Build tools list
        tools = []
        for tool in self.tools.filter(is_active=True):
            tools.append({
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.parameters_schema or {},
                "function_path": tool.builtin_ref or "",  # For builtin tools
                "requires_confirmation": False,
                "is_safe": True,
                "timeout_seconds": 30,
            })

        # Add dynamic tools
        for tool in self.dynamic_tools.filter(is_active=True):
            tools.append({
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.parameters_schema or {},
                "function_path": tool.function_path,
                "requires_confirmation": tool.requires_confirmation,
                "is_safe": tool.is_safe,
                "timeout_seconds": tool.timeout_seconds,
            })

        # Build knowledge list
        knowledge = []
        for k in self.knowledge_sources.filter(is_active=True):
            knowledge.append({
                "name": k.name,
                "type": k.knowledge_type,
                "inclusion_mode": k.inclusion_mode,
                "content": k.content or "",
                "file_path": k.file.name if k.file else "",
                "url": k.url or "",
            })

        # Build sub-agent tools list
        sub_agent_tools = []
        for sub_tool in self.sub_agent_tools.filter(is_active=True).select_related('sub_agent'):
            sub_agent_tools.append(sub_tool.to_config_dict())

        return {
            "schema_version": "1",
            "version": active_version.version if active_version else "1.0",
            "name": self.name,
            "slug": self.slug,
            "description": self.description or "",
            "system_prompt": active_version.system_prompt if active_version else "",
            "model": active_version.model if active_version else "gpt-4o",
            "model_settings": active_version.model_settings if active_version else {},
            "tools": tools,
            "knowledge": knowledge,
            "sub_agent_tools": sub_agent_tools,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "extra": active_version.extra_config if active_version else {},
        }


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


class AgentRevision(models.Model):
    """
    A revision (snapshot) of an agent's complete configuration.

    Every change to an agent creates a new revision, allowing:
    - Full history of changes
    - Ability to restore any previous state
    - Comparison between revisions

    The content field stores a JSON snapshot in the portable AgentConfig format,
    which can be used both in Django and standalone Python scripts.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    agent = models.ForeignKey(
        AgentDefinition,
        on_delete=models.CASCADE,
        related_name='revisions',
    )

    # Auto-incrementing revision number per agent
    revision_number = models.PositiveIntegerField(
        help_text="Revision number (auto-incremented per agent)",
    )

    # The complete agent configuration as JSON (AgentConfig format)
    content = models.JSONField(
        help_text="Complete agent configuration snapshot in AgentConfig format",
    )

    # Metadata
    comment = models.TextField(
        blank=True,
        help_text="Optional description of what changed in this revision",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='agent_revisions',
    )

    class Meta:
        ordering = ['-revision_number']
        unique_together = [('agent', 'revision_number')]
        verbose_name = "Agent Revision"
        verbose_name_plural = "Agent Revisions"

    def __str__(self):
        return f"{self.agent.name} r{self.revision_number}"

    def save(self, *args, **kwargs):
        # Auto-increment revision_number if not set
        if self.revision_number is None:
            last_revision = AgentRevision.objects.filter(
                agent=self.agent
            ).order_by('-revision_number').first()
            self.revision_number = (last_revision.revision_number + 1) if last_revision else 1
        super().save(*args, **kwargs)

    @classmethod
    def create_from_agent(cls, agent: 'AgentDefinition', comment: str = "", user=None) -> 'AgentRevision':
        """
        Create a new revision from the current state of an agent.

        Args:
            agent: The AgentDefinition to snapshot
            comment: Optional description of the change
            user: Optional user who made the change

        Returns:
            The created AgentRevision
        """
        content = agent.to_config_dict()
        return cls.objects.create(
            agent=agent,
            content=content,
            comment=comment,
            created_by=user,
        )

    def restore(self, user=None) -> 'AgentRevision':
        """
        Restore this revision as the current state.

        Creates a new revision with the content from this revision.

        Args:
            user: Optional user performing the restore

        Returns:
            The new revision created from the restore
        """
        return AgentRevision.create_from_agent(
            self.agent,
            comment=f"Restored from revision {self.revision_number}",
            user=user,
        )


class AgentTool(models.Model):
    """
    A tool available to an agent.

    Tools can be:
    - Built-in tools (referenced by name)
    - Custom function tools (with schema)
    - Sub-agent tools (delegate to another agent)

    For SUBAGENT tools, the invocation_mode and context_mode control
    how the sub-agent is called and what context it receives.
    """

    class ToolType(models.TextChoices):
        BUILTIN = 'builtin', 'Built-in Tool'
        FUNCTION = 'function', 'Custom Function'
        SUBAGENT = 'subagent', 'Sub-Agent'

    class InvocationMode(models.TextChoices):
        """How the sub-agent is invoked."""
        DELEGATE = 'delegate', 'Delegate (return result to parent)'
        HANDOFF = 'handoff', 'Handoff (transfer conversation)'

    class ContextMode(models.TextChoices):
        """What context is passed to the sub-agent."""
        FULL = 'full', 'Full conversation history'
        SUMMARY = 'summary', 'Summary + message'
        MESSAGE_ONLY = 'message_only', 'Message only'

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

    # Sub-agent invocation settings (only used when tool_type=SUBAGENT)
    invocation_mode = models.CharField(
        max_length=20,
        choices=InvocationMode.choices,
        default=InvocationMode.DELEGATE,
        help_text="How to invoke the sub-agent (delegate returns result, handoff transfers control)",
    )
    context_mode = models.CharField(
        max_length=20,
        choices=ContextMode.choices,
        default=ContextMode.FULL,
        help_text="What context to pass to the sub-agent",
    )
    max_turns = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="Maximum turns for sub-agent (optional, for delegate mode)",
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
        schema = {
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

        # Add sub-agent specific metadata
        if self.tool_type == self.ToolType.SUBAGENT:
            schema['_meta']['invocation_mode'] = self.invocation_mode
            schema['_meta']['context_mode'] = self.context_mode
            schema['_meta']['max_turns'] = self.max_turns
            # For sub-agent tools, use a standard message-based schema
            schema['function']['parameters'] = {
                'type': 'object',
                'properties': {
                    'message': {
                        'type': 'string',
                        'description': 'The message or task to send to this agent',
                    },
                    'context': {
                        'type': 'string',
                        'description': 'Optional additional context to include',
                    },
                },
                'required': ['message'],
            }

        return schema

    def to_agent_tool(self) -> 'AgentToolCore':
        """
        Convert to agent_runtime_core.AgentTool for execution.

        This creates the core AgentTool object that can be used with
        invoke_agent() and register_agent_tools().

        Returns:
            AgentTool from agent_runtime_core.multi_agent

        Raises:
            ValueError: If tool_type is not SUBAGENT or subagent is not set
        """
        if self.tool_type != self.ToolType.SUBAGENT:
            raise ValueError(f"Cannot convert non-subagent tool to AgentTool: {self.tool_type}")
        if not self.subagent:
            raise ValueError(f"Subagent tool '{self.name}' has no subagent set")

        from agent_runtime_core.multi_agent import (
            AgentTool as AgentToolCore,
            InvocationMode as InvocationModeCore,
            ContextMode as ContextModeCore,
        )

        # Map Django choices to core enums
        invocation_mode_map = {
            self.InvocationMode.DELEGATE: InvocationModeCore.DELEGATE,
            self.InvocationMode.HANDOFF: InvocationModeCore.HANDOFF,
        }
        context_mode_map = {
            self.ContextMode.FULL: ContextModeCore.FULL,
            self.ContextMode.SUMMARY: ContextModeCore.SUMMARY,
            self.ContextMode.MESSAGE_ONLY: ContextModeCore.MESSAGE_ONLY,
        }

        # Get the sub-agent's runtime using the registry (which has database fallback)
        from django_agent_runtime.runtime.registry import get_runtime
        sub_agent_runtime = get_runtime(self.subagent.slug)

        return AgentToolCore(
            agent=sub_agent_runtime,
            name=self.name,
            description=self.description,
            invocation_mode=invocation_mode_map[self.invocation_mode],
            context_mode=context_mode_map[self.context_mode],
            max_turns=self.max_turns,
            metadata={
                'django_tool_id': str(self.id),
                'subagent_slug': self.subagent.slug,
            },
        )


class AgentKnowledge(models.Model):
    """
    Knowledge source for an agent.

    Knowledge can be:
    - Static text (instructions, context)
    - File references (documents to include)
    - Dynamic sources (API endpoints, database queries)

    For RAG mode, content is chunked, embedded, and stored in a vector store
    for similarity-based retrieval at runtime.
    """

    class KnowledgeType(models.TextChoices):
        TEXT = 'text', 'Static Text'
        FILE = 'file', 'File/Document'
        URL = 'url', 'URL/Webpage'
        DYNAMIC = 'dynamic', 'Dynamic Source'

    class EmbeddingStatus(models.TextChoices):
        NOT_INDEXED = 'not_indexed', 'Not Indexed'
        PENDING = 'pending', 'Pending'
        INDEXING = 'indexing', 'Indexing'
        INDEXED = 'indexed', 'Indexed'
        FAILED = 'failed', 'Failed'
        STALE = 'stale', 'Stale (needs re-indexing)'

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

    # ==========================================================================
    # RAG / Vector Store Fields
    # ==========================================================================

    # Embedding status for RAG mode
    embedding_status = models.CharField(
        max_length=20,
        choices=EmbeddingStatus.choices,
        default=EmbeddingStatus.NOT_INDEXED,
        help_text="Status of vector embeddings for RAG",
    )

    # Number of chunks this knowledge was split into
    chunk_count = models.PositiveIntegerField(
        default=0,
        help_text="Number of chunks in vector store",
    )

    # Content hash to detect changes (for re-indexing)
    content_hash = models.CharField(
        max_length=64,
        blank=True,
        help_text="SHA-256 hash of content for change detection",
    )

    # When embeddings were last updated
    indexed_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When this knowledge was last indexed",
    )

    # Error message if indexing failed
    embedding_error = models.TextField(
        blank=True,
        help_text="Error message if embedding failed",
    )

    # RAG-specific settings (chunk size, overlap, etc.)
    rag_config = models.JSONField(
        default=dict,
        blank=True,
        help_text="RAG configuration: chunk_size, chunk_overlap, etc.",
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

    def get_content_hash(self) -> str:
        """Calculate SHA-256 hash of the content."""
        import hashlib
        content = self.get_indexable_content()
        return hashlib.sha256(content.encode('utf-8')).hexdigest()

    def get_indexable_content(self) -> str:
        """Get the content that should be indexed."""
        if self.knowledge_type == 'text':
            return self.content or ''
        elif self.knowledge_type == 'file' and self.file:
            # TODO: Extract text from file (PDF, DOCX, etc.)
            try:
                return self.file.read().decode('utf-8')
            except Exception:
                return ''
        elif self.knowledge_type == 'url':
            # Content should be fetched and stored in content field
            return self.content or ''
        return ''

    def needs_reindexing(self) -> bool:
        """Check if this knowledge needs to be re-indexed."""
        if self.inclusion_mode != 'rag':
            return False
        if self.embedding_status in ['not_indexed', 'failed', 'stale']:
            return True
        # Check if content has changed
        current_hash = self.get_content_hash()
        return current_hash != self.content_hash

    def to_dict(self) -> dict:
        """Convert to dictionary for configuration."""
        result = {
            'id': str(self.id),
            'name': self.name,
            'type': self.knowledge_type,
            'inclusion_mode': self.inclusion_mode,
            'content': self.content if self.knowledge_type == 'text' else None,
            'file': self.file.url if self.file else None,
            'url': self.url if self.knowledge_type == 'url' else None,
            'dynamic_config': self.dynamic_config if self.knowledge_type == 'dynamic' else None,
        }
        # Add RAG metadata if applicable
        if self.inclusion_mode == 'rag':
            result['rag'] = {
                'status': self.embedding_status,
                'chunk_count': self.chunk_count,
                'indexed_at': self.indexed_at.isoformat() if self.indexed_at else None,
                'config': self.rag_config,
            }
        return result


class DiscoveredFunction(models.Model):
    """
    A function discovered from scanning the Django project.

    This is a staging area for functions before they become tools.
    Stores metadata about discovered functions for review and selection.
    """

    class FunctionType(models.TextChoices):
        FUNCTION = 'function', 'Standalone Function'
        METHOD = 'method', 'Class Method'
        VIEW = 'view', 'Django View'
        MODEL_METHOD = 'model_method', 'Model Method'
        MANAGER_METHOD = 'manager_method', 'Manager Method'
        UTILITY = 'utility', 'Utility Function'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # Discovery metadata
    name = models.CharField(
        max_length=100,
        help_text="Function name",
    )
    module_path = models.CharField(
        max_length=500,
        help_text="Full module path (e.g., 'myapp.utils')",
    )
    function_path = models.CharField(
        max_length=600,
        help_text="Full function path (e.g., 'myapp.utils.calculate_tax')",
    )
    function_type = models.CharField(
        max_length=20,
        choices=FunctionType.choices,
        default=FunctionType.FUNCTION,
    )

    # Class info (for methods)
    class_name = models.CharField(
        max_length=100,
        blank=True,
        help_text="Class name if this is a method",
    )

    # Source info
    file_path = models.CharField(
        max_length=500,
        help_text="Relative file path from project root",
    )
    line_number = models.PositiveIntegerField(
        help_text="Line number where function is defined",
    )

    # Function signature
    signature = models.TextField(
        help_text="Function signature string",
    )
    docstring = models.TextField(
        blank=True,
        help_text="Function docstring",
    )

    # Parsed parameters
    parameters = models.JSONField(
        default=list,
        help_text="List of parameter info dicts",
    )
    return_type = models.CharField(
        max_length=200,
        blank=True,
        help_text="Return type annotation if available",
    )

    # Analysis flags
    is_async = models.BooleanField(
        default=False,
        help_text="Whether function is async",
    )
    has_side_effects = models.BooleanField(
        default=False,
        help_text="Whether function likely has side effects (writes to DB, etc.)",
    )
    is_private = models.BooleanField(
        default=False,
        help_text="Whether function name starts with underscore",
    )

    # Selection status
    is_selected = models.BooleanField(
        default=False,
        help_text="Whether this function has been selected to become a tool",
    )

    # Scan tracking
    scan_session = models.CharField(
        max_length=100,
        help_text="Identifier for the scan session that discovered this",
    )
    discovered_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['module_path', 'name']
        unique_together = [('function_path', 'scan_session')]
        verbose_name = "Discovered Function"
        verbose_name_plural = "Discovered Functions"

    def __str__(self):
        return f"{self.function_path} ({self.function_type})"


class DynamicTool(models.Model):
    """
    A dynamically discovered and stored tool.

    Unlike AgentTool which references built-in tools or defines schemas,
    DynamicTool stores the actual function path and can execute real
    Django project functions.
    """

    class ExecutionMode(models.TextChoices):
        DIRECT = 'direct', 'Direct Import & Call'
        SANDBOXED = 'sandboxed', 'Sandboxed Execution'
        SUBPROCESS = 'subprocess', 'Subprocess Isolation'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # Link to agent
    agent = models.ForeignKey(
        AgentDefinition,
        on_delete=models.CASCADE,
        related_name='dynamic_tools',
    )

    # Tool identification
    name = models.CharField(
        max_length=100,
        help_text="Tool name (must be unique within agent)",
    )
    description = models.TextField(
        help_text="Description of what the tool does (shown to LLM)",
    )

    # Function reference
    function_path = models.CharField(
        max_length=600,
        help_text="Full import path to the function (e.g., 'myapp.utils.calculate_tax')",
    )

    # Source reference (for traceability)
    source_file = models.CharField(
        max_length=500,
        blank=True,
        help_text="Source file path",
    )
    source_line = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="Source line number",
    )

    # Schema
    parameters_schema = models.JSONField(
        default=dict,
        help_text="JSON Schema for tool parameters",
    )

    # Execution settings
    execution_mode = models.CharField(
        max_length=20,
        choices=ExecutionMode.choices,
        default=ExecutionMode.DIRECT,
    )
    timeout_seconds = models.PositiveIntegerField(
        default=30,
        help_text="Maximum execution time in seconds",
    )

    # Security settings
    is_safe = models.BooleanField(
        default=False,
        help_text="Whether this tool is considered safe (no side effects)",
    )
    requires_confirmation = models.BooleanField(
        default=True,
        help_text="Whether to ask user before executing",
    )
    allowed_for_auto_execution = models.BooleanField(
        default=False,
        help_text="Whether agent can execute without human approval",
    )

    # Whitelist/blacklist for imports
    allowed_imports = models.JSONField(
        default=list,
        blank=True,
        help_text="List of allowed import patterns for sandboxed execution",
    )
    blocked_imports = models.JSONField(
        default=list,
        blank=True,
        help_text="List of blocked import patterns",
    )

    # Status
    is_active = models.BooleanField(default=True)
    is_verified = models.BooleanField(
        default=False,
        help_text="Whether this tool has been manually verified",
    )

    # Versioning
    version = models.PositiveIntegerField(default=1)

    # Audit
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='created_dynamic_tools',
    )

    # Link to discovered function (if created from scan)
    discovered_function = models.ForeignKey(
        DiscoveredFunction,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='tools',
    )

    class Meta:
        ordering = ['name']
        unique_together = [('agent', 'name')]
        verbose_name = "Dynamic Tool"
        verbose_name_plural = "Dynamic Tools"

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
                'tool_type': 'dynamic',
                'function_path': self.function_path,
                'execution_mode': self.execution_mode,
                'timeout': self.timeout_seconds,
                'requires_confirmation': self.requires_confirmation,
            },
        }


class DynamicToolExecution(models.Model):
    """
    Audit log for dynamic tool executions.

    Records every execution of a dynamic tool for security
    auditing and debugging.
    """

    class ExecutionStatus(models.TextChoices):
        PENDING = 'pending', 'Pending'
        RUNNING = 'running', 'Running'
        SUCCESS = 'success', 'Success'
        FAILED = 'failed', 'Failed'
        TIMEOUT = 'timeout', 'Timeout'
        BLOCKED = 'blocked', 'Blocked (Security)'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # Tool reference
    tool = models.ForeignKey(
        DynamicTool,
        on_delete=models.CASCADE,
        related_name='executions',
    )

    # Execution context
    agent_run_id = models.UUIDField(
        null=True,
        blank=True,
        help_text="ID of the agent run that triggered this execution",
    )

    # Input/Output
    input_arguments = models.JSONField(
        default=dict,
        help_text="Arguments passed to the tool",
    )
    output_result = models.JSONField(
        null=True,
        blank=True,
        help_text="Result returned by the tool",
    )
    error_message = models.TextField(
        blank=True,
        help_text="Error message if execution failed",
    )
    error_traceback = models.TextField(
        blank=True,
        help_text="Full traceback if execution failed",
    )

    # Status
    status = models.CharField(
        max_length=20,
        choices=ExecutionStatus.choices,
        default=ExecutionStatus.PENDING,
    )

    # Timing
    started_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    duration_ms = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="Execution duration in milliseconds",
    )

    # Security
    was_sandboxed = models.BooleanField(default=False)
    user_confirmed = models.BooleanField(
        default=False,
        help_text="Whether user confirmed execution",
    )

    # User context
    executed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )

    class Meta:
        ordering = ['-started_at']
        verbose_name = "Dynamic Tool Execution"
        verbose_name_plural = "Dynamic Tool Executions"

    def __str__(self):
        return f"{self.tool.name} - {self.status} ({self.started_at})"


# =============================================================================
# Sub-Agent Tool Model
# =============================================================================


class SubAgentTool(models.Model):
    """
    A tool that delegates to another agent (sub-agent).

    This enables the "agent-as-tool" pattern where one agent can invoke
    another agent as if it were a tool. The parent agent can delegate
    specific tasks to specialized sub-agents.

    Example:
        A "Customer Support Triage" agent might have sub-agent tools for:
        - billing_specialist: Handles billing questions
        - technical_specialist: Handles technical issues
    """

    class ContextMode(models.TextChoices):
        """How much context to pass to the sub-agent."""
        MESSAGE_ONLY = 'message_only', 'Message Only (just the task)'
        SUMMARY = 'summary', 'Summary (brief context)'
        FULL = 'full', 'Full (entire conversation)'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # The agent that owns this tool (parent)
    parent_agent = models.ForeignKey(
        AgentDefinition,
        on_delete=models.CASCADE,
        related_name='sub_agent_tools',
        help_text='The agent that can use this sub-agent tool',
    )

    # The agent being delegated to (sub-agent)
    sub_agent = models.ForeignKey(
        AgentDefinition,
        on_delete=models.CASCADE,
        related_name='used_as_sub_agent_in',
        help_text='The agent that will handle delegated tasks',
    )

    # Tool configuration
    name = models.CharField(
        max_length=100,
        help_text='Tool name (snake_case, e.g., billing_specialist)',
    )
    description = models.TextField(
        help_text='When to use this sub-agent (shown to the parent agent)',
    )

    # Context passing configuration
    context_mode = models.CharField(
        max_length=20,
        choices=ContextMode.choices,
        default=ContextMode.MESSAGE_ONLY,
        help_text='How much conversation context to pass to the sub-agent',
    )

    # Status
    is_active = models.BooleanField(default=True)

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Sub-Agent Tool"
        verbose_name_plural = "Sub-Agent Tools"
        unique_together = [('parent_agent', 'name')]
        ordering = ['name']

    def __str__(self):
        return f"{self.parent_agent.slug} -> {self.name} ({self.sub_agent.slug})"

    def to_config_dict(self) -> dict:
        """Convert to the config format used by agent_runtime_core."""
        return {
            "name": self.name,
            "description": self.description,
            "agent_slug": self.sub_agent.slug,
            "context_mode": self.context_mode,
        }


# =============================================================================
# Multi-Agent System Models
# =============================================================================


class AgentSystem(models.Model):
    """
    A multi-agent system - a named collection of agents that work together.

    An AgentSystem groups related agents and provides:
    - Coordinated versioning (publish all agents together)
    - Dependency tracking (which agents call which)
    - Entry point definition (which agent handles initial requests)

    Example systems:
    - "Customer Support" with triage, billing, and technical agents
    - "Sales Pipeline" with lead qualification and proposal agents
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # Identity
    slug = models.SlugField(
        max_length=100,
        unique=True,
        help_text="Unique identifier for this system",
    )
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)

    # Shared knowledge for all agents in this system
    # This is a list of SharedKnowledge items that get injected into all member agents
    # Format: [{"key": "...", "title": "...", "content": "...", "inject_as": "system|context|knowledge", "priority": 0, "enabled": true}]
    shared_knowledge = models.JSONField(
        default=list,
        blank=True,
        help_text="Shared knowledge items that apply to all agents in this system",
    )

    # The entry point agent (receives initial requests)
    entry_agent = models.ForeignKey(
        AgentDefinition,
        on_delete=models.PROTECT,
        related_name='entry_point_for_systems',
        help_text="The agent that handles initial requests to this system",
    )

    # Owner (for multi-tenant scenarios)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='agent_systems',
    )

    # Status
    is_active = models.BooleanField(default=True)

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-updated_at']
        verbose_name = "Agent System"
        verbose_name_plural = "Agent Systems"

    def __str__(self):
        return f"{self.name} ({self.slug})"

    def get_all_agents(self) -> list[AgentDefinition]:
        """Get all agents in this system (via members)."""
        return [m.agent for m in self.members.select_related('agent').all()]

    def get_dependency_graph(self) -> dict:
        """
        Build a dependency graph showing which agents call which.

        Returns:
            Dict mapping agent_slug -> list of sub-agent slugs it calls
        """
        graph = {}
        for member in self.members.select_related('agent').all():
            agent = member.agent
            sub_agents = []
            for tool in agent.tools.filter(
                tool_type=AgentTool.ToolType.SUBAGENT,
                is_active=True,
            ).select_related('subagent'):
                if tool.subagent:
                    sub_agents.append(tool.subagent.slug)
            graph[agent.slug] = sub_agents
        return graph

    def get_system_context(self):
        """
        Convert the shared_knowledge JSON to a SystemContext object.

        Returns:
            SystemContext object with shared knowledge items, or None if no shared knowledge
        """
        from agent_runtime_core.multi_agent import SystemContext, SharedKnowledge, InjectMode

        if not self.shared_knowledge:
            return None

        knowledge_items = []
        for item in self.shared_knowledge:
            try:
                knowledge_items.append(SharedKnowledge(
                    key=item.get('key', ''),
                    title=item.get('title', ''),
                    content=item.get('content', ''),
                    inject_as=InjectMode(item.get('inject_as', 'system')),
                    priority=item.get('priority', 0),
                    enabled=item.get('enabled', True),
                    metadata=item.get('metadata', {}),
                ))
            except (KeyError, ValueError) as e:
                # Skip invalid items but log
                import logging
                logging.getLogger(__name__).warning(
                    f"Invalid shared knowledge item in system {self.slug}: {e}"
                )

        if not knowledge_items:
            return None

        return SystemContext(
            system_id=str(self.id),
            system_name=self.name,
            shared_knowledge=knowledge_items,
            metadata={
                'slug': self.slug,
                'description': self.description,
            },
        )


class AgentSystemMember(models.Model):
    """
    Links an agent to a system with a role.

    Roles help document the purpose of each agent in the system:
    - "entry_point": Handles initial requests (should match system.entry_agent)
    - "specialist": Domain-specific agent (billing, technical, etc.)
    - "utility": Shared utility agent (summarizer, translator, etc.)
    """

    class Role(models.TextChoices):
        ENTRY_POINT = 'entry_point', 'Entry Point'
        SPECIALIST = 'specialist', 'Specialist'
        UTILITY = 'utility', 'Utility'
        SUPERVISOR = 'supervisor', 'Supervisor'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    system = models.ForeignKey(
        AgentSystem,
        on_delete=models.CASCADE,
        related_name='members',
    )
    agent = models.ForeignKey(
        AgentDefinition,
        on_delete=models.CASCADE,
        related_name='system_memberships',
    )

    # Role in the system
    role = models.CharField(
        max_length=20,
        choices=Role.choices,
        default=Role.SPECIALIST,
    )

    # Optional notes about this agent's role
    notes = models.TextField(blank=True)

    # Ordering for display
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['order', 'role']
        unique_together = [('system', 'agent')]
        verbose_name = "Agent System Member"
        verbose_name_plural = "Agent System Members"

    def __str__(self):
        return f"{self.system.name} - {self.agent.name} ({self.role})"


class AgentSystemVersion(models.Model):
    """
    A versioned release of a multi-agent system.

    When you publish a system version, it snapshots the current state
    of all member agents, creating AgentSystemSnapshot records that
    pin specific agent revisions.

    This allows:
    - Coordinated releases of multiple agents
    - Rollback to previous system states
    - Testing before making a version active
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    system = models.ForeignKey(
        AgentSystem,
        on_delete=models.CASCADE,
        related_name='versions',
    )

    # Version identifier
    version = models.CharField(
        max_length=50,
        help_text="Version string (e.g., '1.0.0', '2024-01-15')",
    )

    # Status
    is_active = models.BooleanField(
        default=False,
        help_text="Whether this is the currently deployed version",
    )
    is_draft = models.BooleanField(
        default=True,
        help_text="Whether this version is still being prepared",
    )

    # Release notes
    notes = models.TextField(
        blank=True,
        help_text="Release notes describing changes in this version",
    )

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    published_at = models.DateTimeField(null=True, blank=True)

    # Who created/published
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='created_system_versions',
    )

    class Meta:
        ordering = ['-created_at']
        unique_together = [('system', 'version')]
        verbose_name = "Agent System Version"
        verbose_name_plural = "Agent System Versions"

    def __str__(self):
        status = "active" if self.is_active else ("draft" if self.is_draft else "archived")
        return f"{self.system.name} v{self.version} ({status})"

    def save(self, *args, **kwargs):
        # Ensure only one active version per system
        if self.is_active:
            AgentSystemVersion.objects.filter(
                system=self.system,
                is_active=True,
            ).exclude(pk=self.pk).update(is_active=False)
        super().save(*args, **kwargs)

    def export_config(self, embed_agents: bool = True) -> dict:
        """
        Export this system version as a portable configuration.

        Args:
            embed_agents: If True, embed full agent configs inline.
                         If False, only include agent slugs (for registry lookup).

        Returns:
            Dictionary that can be loaded by agent_runtime_core
        """
        from datetime import datetime

        # Get the entry agent's snapshot
        entry_snapshot = self.snapshots.filter(
            agent=self.system.entry_agent
        ).select_related('agent', 'pinned_revision').first()

        if not entry_snapshot:
            raise ValueError(f"No snapshot for entry agent {self.system.entry_agent.slug}")

        # Build the entry agent config
        entry_config = entry_snapshot.get_agent_config()

        if embed_agents:
            # Embed all sub-agent configs
            all_agents = {}
            for snapshot in self.snapshots.select_related('agent', 'pinned_revision').all():
                agent_config = snapshot.get_agent_config()
                all_agents[snapshot.agent.slug] = agent_config

            # Wire up sub-agent tools with embedded configs
            entry_config = self._embed_sub_agents(entry_config, all_agents)

        return {
            "schema_version": "1",
            "system_slug": self.system.slug,
            "system_name": self.system.name,
            "system_version": self.version,
            "entry_agent": entry_config,
            "exported_at": datetime.utcnow().isoformat() + "Z",
        }

    def _embed_sub_agents(self, config: dict, all_agents: dict) -> dict:
        """Recursively embed sub-agent configs into an agent config."""
        if "sub_agent_tools" not in config:
            config["sub_agent_tools"] = []

        # Find sub-agent tools and embed their configs
        for sub_tool in config.get("sub_agent_tools", []):
            agent_slug = sub_tool.get("agent_slug")
            if agent_slug and agent_slug in all_agents:
                sub_config = all_agents[agent_slug]
                # Recursively embed nested sub-agents
                sub_config = self._embed_sub_agents(sub_config, all_agents)
                sub_tool["agent_config"] = sub_config

        return config


class AgentSystemSnapshot(models.Model):
    """
    A snapshot of a specific agent within a system version.

    This pins a specific agent revision to a system version,
    ensuring reproducible deployments.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    system_version = models.ForeignKey(
        AgentSystemVersion,
        on_delete=models.CASCADE,
        related_name='snapshots',
    )

    agent = models.ForeignKey(
        AgentDefinition,
        on_delete=models.PROTECT,
        related_name='system_snapshots',
    )

    # The specific revision pinned for this system version
    pinned_revision = models.ForeignKey(
        AgentRevision,
        on_delete=models.PROTECT,
        related_name='system_snapshots',
        help_text="The specific agent revision used in this system version",
    )

    # Optional tool configuration overrides for this system
    # (e.g., different invocation_mode or context_mode)
    tool_config_overrides = models.JSONField(
        default=dict,
        blank=True,
        help_text="Overrides for sub-agent tool configurations in this system",
    )

    class Meta:
        unique_together = [('system_version', 'agent')]
        verbose_name = "Agent System Snapshot"
        verbose_name_plural = "Agent System Snapshots"

    def __str__(self):
        return f"{self.system_version} - {self.agent.name} r{self.pinned_revision.revision_number}"

    def get_agent_config(self) -> dict:
        """
        Get the agent configuration from the pinned revision.

        Returns:
            The agent config dict from the pinned revision
        """
        return self.pinned_revision.content.copy()


class SpecDocument(models.Model):
    """
    A specification document for describing agent behavior in plain English.

    Documents form a tree structure that can be:
    - Viewed as a single unified document for human review
    - Linked to specific agents for two-way sync
    - Versioned for full history tracking

    The tree structure allows organizing specs hierarchically:
    - Root document: "Company AI Agents"
      - Child: "Customer Support Agents"
        - Child: "Billing Support" (linked to billing-agent)
        - Child: "Technical Support" (linked to tech-agent)
      - Child: "Internal Tools"
        - Child: "HR Assistant" (linked to hr-agent)
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # Tree structure
    parent = models.ForeignKey(
        'self',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='children',
        help_text="Parent document (null for root documents)",
    )

    # Ordering within siblings
    order = models.PositiveIntegerField(
        default=0,
        help_text="Order among sibling documents",
    )

    # Document content
    title = models.CharField(
        max_length=255,
        help_text="Document title (used as heading when rendering)",
    )

    content = models.TextField(
        blank=True,
        help_text="Markdown content of this document section",
    )

    # Optional link to an agent
    # When linked, changes to this doc update the agent's spec field
    linked_agent = models.ForeignKey(
        AgentDefinition,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='spec_documents',
        help_text="Agent whose spec is defined by this document",
    )

    # Ownership
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='spec_documents',
    )

    # Metadata
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # Current version number (incremented on each save)
    current_version = models.PositiveIntegerField(default=1)

    class Meta:
        ordering = ['parent_id', 'order', 'title']
        verbose_name = "Spec Document"
        verbose_name_plural = "Spec Documents"

    def __str__(self):
        if self.linked_agent:
            return f"{self.title} → {self.linked_agent.name}"
        return self.title

    def save(self, *args, **kwargs):
        # Check if content changed (for versioning)
        create_version = False
        if self.pk:
            try:
                old = SpecDocument.objects.get(pk=self.pk)
                if old.content != self.content or old.title != self.title:
                    create_version = True
                    self.current_version += 1
            except SpecDocument.DoesNotExist:
                create_version = True
        else:
            create_version = True

        super().save(*args, **kwargs)

        # Create version snapshot
        if create_version:
            SpecDocumentVersion.objects.create(
                document=self,
                version_number=self.current_version,
                title=self.title,
                content=self.content,
            )
        # Note: We no longer sync to agent.spec field - SpecDocument is the source of truth

    def get_ancestors(self):
        """Get all ancestor documents from root to parent."""
        ancestors = []
        current = self.parent
        while current:
            ancestors.insert(0, current)
            current = current.parent
        return ancestors

    def get_descendants(self):
        """Get all descendant documents in tree order."""
        descendants = []
        for child in self.children.all().order_by('order', 'title'):
            descendants.append(child)
            descendants.extend(child.get_descendants())
        return descendants

    def get_full_path(self):
        """Get the full path as a string (e.g., 'Root / Child / Grandchild')."""
        ancestors = self.get_ancestors()
        path_parts = [a.title for a in ancestors] + [self.title]
        return ' / '.join(path_parts)

    def render_tree_as_markdown(self, level=1):
        """
        Render this document and all descendants as a single markdown document.

        Args:
            level: Heading level to start at (1 = #, 2 = ##, etc.)

        Returns:
            Complete markdown string
        """
        parts = []

        # Add this document's content
        heading = '#' * min(level, 6)
        parts.append(f"{heading} {self.title}")

        if self.linked_agent:
            parts.append(f"*Linked to agent: `{self.linked_agent.slug}`*")

        if self.content:
            parts.append("")
            parts.append(self.content)

        # Add children
        for child in self.children.all().order_by('order', 'title'):
            parts.append("")
            parts.append(child.render_tree_as_markdown(level=level + 1))

        return '\n'.join(parts)

    @classmethod
    def get_root_documents(cls, owner=None):
        """Get all root documents (no parent), optionally filtered by owner."""
        qs = cls.objects.filter(parent__isnull=True)
        if owner:
            qs = qs.filter(owner=owner)
        return qs.order_by('order', 'title')


class SpecDocumentVersion(models.Model):
    """
    An immutable version snapshot of a spec document.

    Created automatically whenever a document's content or title changes.
    Allows full history tracking and rollback.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    document = models.ForeignKey(
        SpecDocument,
        on_delete=models.CASCADE,
        related_name='versions',
    )

    # Version number (matches document.current_version at time of creation)
    version_number = models.PositiveIntegerField()

    # Snapshot of content at this version
    title = models.CharField(max_length=255)
    content = models.TextField(blank=True)

    # Metadata
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='spec_document_versions',
    )

    # Optional change description
    change_summary = models.CharField(
        max_length=255,
        blank=True,
        help_text="Brief description of what changed",
    )

    class Meta:
        ordering = ['-version_number']
        unique_together = [('document', 'version_number')]
        verbose_name = "Spec Document Version"
        verbose_name_plural = "Spec Document Versions"

    def __str__(self):
        return f"{self.document.title} v{self.version_number}"

    def get_diff_from_previous(self):
        """
        Get a simple diff from the previous version.

        Returns:
            Dict with 'title_changed', 'content_changed', 'previous_version'
        """
        try:
            previous = SpecDocumentVersion.objects.get(
                document=self.document,
                version_number=self.version_number - 1,
            )
            return {
                'title_changed': previous.title != self.title,
                'content_changed': previous.content != self.content,
                'previous_version': previous.version_number,
                'previous_title': previous.title,
            }
        except SpecDocumentVersion.DoesNotExist:
            return {
                'title_changed': False,
                'content_changed': False,
                'previous_version': None,
                'previous_title': None,
            }

    def restore(self):
        """
        Restore the document to this version.

        Creates a new version with the restored content.
        """
        self.document.title = self.title
        self.document.content = self.content
        self.document.save()  # This will create a new version


# =============================================================================
# Collaborator Models for Multi-User Access Control
# =============================================================================


class CollaboratorRole(models.TextChoices):
    """Role choices for collaborators on agents and systems."""
    VIEWER = 'viewer', 'Viewer'      # Can view but not edit
    EDITOR = 'editor', 'Editor'      # Can view and edit
    ADMIN = 'admin', 'Admin'         # Can view, edit, and manage collaborators


class AgentCollaborator(models.Model):
    """
    Grants a user access to an agent with a specific role.

    This enables multi-user collaboration on agents beyond the single owner.
    The owner always has full access; collaborators have role-based access.

    Roles:
    - viewer: Can view the agent and test it
    - editor: Can view and edit the agent configuration
    - admin: Can view, edit, and manage other collaborators
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    agent = models.ForeignKey(
        AgentDefinition,
        on_delete=models.CASCADE,
        related_name='collaborators',
        help_text="The agent this collaborator has access to",
    )

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='agent_collaborations',
        help_text="The user who has been granted access",
    )

    role = models.CharField(
        max_length=20,
        choices=CollaboratorRole.choices,
        default=CollaboratorRole.VIEWER,
        help_text="The level of access granted to this user",
    )

    # Audit fields
    added_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='agent_collaborators_added',
        help_text="The user who added this collaborator",
    )
    added_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['role', 'user__email']
        unique_together = [('agent', 'user')]
        verbose_name = "Agent Collaborator"
        verbose_name_plural = "Agent Collaborators"

    def __str__(self):
        return f"{self.user} - {self.agent.name} ({self.role})"

    @property
    def can_view(self) -> bool:
        """All roles can view."""
        return True

    @property
    def can_edit(self) -> bool:
        """Editors and admins can edit."""
        return self.role in [CollaboratorRole.EDITOR, CollaboratorRole.ADMIN]

    @property
    def can_admin(self) -> bool:
        """Only admins can manage collaborators."""
        return self.role == CollaboratorRole.ADMIN


class SystemCollaborator(models.Model):
    """
    Grants a user access to an agent system with a specific role.

    This enables multi-user collaboration on systems beyond the single owner.
    The owner always has full access; collaborators have role-based access.

    Roles:
    - viewer: Can view the system and test it
    - editor: Can view and edit the system configuration
    - admin: Can view, edit, and manage other collaborators
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    system = models.ForeignKey(
        AgentSystem,
        on_delete=models.CASCADE,
        related_name='collaborators',
        help_text="The system this collaborator has access to",
    )

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='system_collaborations',
        help_text="The user who has been granted access",
    )

    role = models.CharField(
        max_length=20,
        choices=CollaboratorRole.choices,
        default=CollaboratorRole.VIEWER,
        help_text="The level of access granted to this user",
    )

    # Audit fields
    added_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='system_collaborators_added',
        help_text="The user who added this collaborator",
    )
    added_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['role', 'user__email']
        unique_together = [('system', 'user')]
        verbose_name = "System Collaborator"
        verbose_name_plural = "System Collaborators"

    def __str__(self):
        return f"{self.user} - {self.system.name} ({self.role})"

    @property
    def can_view(self) -> bool:
        """All roles can view."""
        return True

    @property
    def can_edit(self) -> bool:
        """Editors and admins can edit."""
        return self.role in [CollaboratorRole.EDITOR, CollaboratorRole.ADMIN]

    @property
    def can_admin(self) -> bool:
        """Only admins can manage collaborators."""
        return self.role == CollaboratorRole.ADMIN
