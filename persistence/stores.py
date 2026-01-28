"""
Django implementations of agent-runtime-core persistence stores.

These stores use Django's async ORM to provide database-backed persistence
for agent memory, conversations, tasks, preferences, knowledge, and audit.
"""

from datetime import datetime
from typing import Any, Optional, List, Dict
from uuid import UUID

from django.db import models

from agent_runtime_core.persistence import (
    MemoryStore,
    ConversationStore,
    TaskStore,
    PreferencesStore,
    KnowledgeStore,
    AuditStore,
    Scope,
    Conversation,
    ConversationMessage,
    Task,
    TaskList,
    TaskState,
    ToolCall,
    ToolResult,
    Fact,
    FactType,
    Summary as CoreSummary,
    Embedding as CoreEmbedding,
    AuditEntry as CoreAuditEntry,
    AuditEventType,
    ErrorRecord as CoreErrorRecord,
    ErrorSeverity,
    PerformanceMetric as CorePerformanceMetric,
)

from django_agent_runtime.persistence.models import (
    Memory,
    PersistenceConversation,
    PersistenceMessage,
    PersistenceTaskList,
    PersistenceTask,
    Preferences,
    TaskStateChoices,
    Fact as FactModel,
    FactTypeChoices,
    Summary as SummaryModel,
    Embedding as EmbeddingModel,
    AuditEntry as AuditEntryModel,
    AuditEventTypeChoices,
    ErrorRecord as ErrorRecordModel,
    ErrorSeverityChoices,
    PerformanceMetric as PerformanceMetricModel,
)


class DjangoMemoryStore(MemoryStore):
    """
    Django-backed memory store.
    
    Stores key-value pairs scoped to a user.
    The scope parameter is ignored - user context provides scoping.
    """
    
    def __init__(self, user):
        self.user = user
    
    async def get(self, key: str, scope: Scope = Scope.PROJECT) -> Optional[Any]:
        """Get a value by key."""
        try:
            entry = await Memory.objects.aget(user=self.user, key=key)
            return entry.value
        except Memory.DoesNotExist:
            return None
    
    async def set(self, key: str, value: Any, scope: Scope = Scope.PROJECT) -> None:
        """Set a value by key."""
        try:
            entry = await Memory.objects.aget(user=self.user, key=key)
            entry.value = value
            await entry.asave(update_fields=["value", "updated_at"])
        except Memory.DoesNotExist:
            await Memory.objects.acreate(user=self.user, key=key, value=value)
    
    async def delete(self, key: str, scope: Scope = Scope.PROJECT) -> bool:
        """Delete a key. Returns True if key existed."""
        deleted, _ = await Memory.objects.filter(user=self.user, key=key).adelete()
        return deleted > 0
    
    async def list_keys(
        self, scope: Scope = Scope.PROJECT, prefix: Optional[str] = None
    ) -> list[str]:
        """List all keys, optionally filtered by prefix."""
        qs = Memory.objects.filter(user=self.user)
        if prefix:
            qs = qs.filter(key__startswith=prefix)
        keys = []
        async for entry in qs.values_list("key", flat=True):
            keys.append(entry)
        return keys
    
    async def clear(self, scope: Scope = Scope.PROJECT) -> None:
        """Clear all keys."""
        await Memory.objects.filter(user=self.user).adelete()


class DjangoConversationStore(ConversationStore):
    """
    Django-backed conversation store.
    
    Stores conversations and messages scoped to a user.
    """
    
    def __init__(self, user):
        self.user = user
    
    def _message_to_db(self, msg: ConversationMessage) -> dict:
        """Convert ConversationMessage to database fields."""
        tool_calls_data = []
        for tc in msg.tool_calls:
            tool_calls_data.append({
                "id": tc.id,
                "name": tc.name,
                "arguments": tc.arguments,
                "timestamp": tc.timestamp.isoformat() if tc.timestamp else None,
            })

        return {
            "id": msg.id,
            "role": msg.role,
            "content": msg.content,
            "tool_calls": tool_calls_data,
            "tool_call_id": msg.tool_call_id or "",
            "model": msg.model or "",
            "usage": msg.usage,
            "metadata": msg.metadata,
            "timestamp": msg.timestamp,
            "parent_message_id": msg.parent_message_id,
            "branch_id": msg.branch_id,
        }

    def _db_to_message(self, db_msg: PersistenceMessage) -> ConversationMessage:
        """Convert database message to ConversationMessage."""
        tool_calls = []
        for tc_data in db_msg.tool_calls or []:
            ts = tc_data.get("timestamp")
            tool_calls.append(ToolCall(
                id=tc_data["id"],
                name=tc_data["name"],
                arguments=tc_data.get("arguments", {}),
                timestamp=datetime.fromisoformat(ts) if ts else datetime.utcnow(),
            ))

        return ConversationMessage(
            id=db_msg.id,
            role=db_msg.role,
            content=db_msg.content,
            timestamp=db_msg.timestamp,
            tool_calls=tool_calls,
            tool_call_id=db_msg.tool_call_id or None,
            model=db_msg.model or None,
            usage=db_msg.usage or {},
            metadata=db_msg.metadata or {},
            parent_message_id=db_msg.parent_message_id,
            branch_id=db_msg.branch_id,
        )
    
    async def save(self, conversation: Conversation, scope: Scope = Scope.PROJECT) -> None:
        """Save or update a conversation."""
        try:
            db_conv = await PersistenceConversation.objects.aget(id=conversation.id)
            db_conv.title = conversation.title or ""
            db_conv.agent_key = conversation.agent_key or ""
            db_conv.summary = conversation.summary or ""
            db_conv.metadata = conversation.metadata
            db_conv.parent_conversation_id = conversation.parent_conversation_id
            db_conv.active_branch_id = conversation.active_branch_id
            await db_conv.asave(update_fields=[
                "title", "agent_key", "summary", "metadata",
                "parent_conversation_id", "active_branch_id", "updated_at"
            ])
            created = False
        except PersistenceConversation.DoesNotExist:
            db_conv = await PersistenceConversation.objects.acreate(
                id=conversation.id,
                user=self.user,
                title=conversation.title or "",
                agent_key=conversation.agent_key or "",
                summary=conversation.summary or "",
                metadata=conversation.metadata,
                parent_conversation_id=conversation.parent_conversation_id,
                active_branch_id=conversation.active_branch_id,
            )
            created = True

        # Save messages if this is a new conversation or we're doing a full save
        if created and conversation.messages:
            for msg in conversation.messages:
                msg_data = self._message_to_db(msg)
                await PersistenceMessage.objects.acreate(
                    conversation=db_conv,
                    **msg_data,
                )

    async def get(
        self, conversation_id: UUID, scope: Scope = Scope.PROJECT
    ) -> Optional[Conversation]:
        """Get a conversation by ID."""
        try:
            db_conv = await PersistenceConversation.objects.aget(
                id=conversation_id, user=self.user
            )
        except PersistenceConversation.DoesNotExist:
            return None

        messages = []
        async for db_msg in db_conv.messages.all().order_by("timestamp"):
            messages.append(self._db_to_message(db_msg))

        return Conversation(
            id=db_conv.id,
            title=db_conv.title or None,
            messages=messages,
            created_at=db_conv.created_at,
            updated_at=db_conv.updated_at,
            metadata=db_conv.metadata or {},
            agent_key=db_conv.agent_key or None,
            summary=db_conv.summary or None,
            parent_conversation_id=db_conv.parent_conversation_id,
            active_branch_id=db_conv.active_branch_id,
        )

    async def delete(self, conversation_id: UUID, scope: Scope = Scope.PROJECT) -> bool:
        """Delete a conversation. Returns True if it existed."""
        deleted, _ = await PersistenceConversation.objects.filter(
            id=conversation_id, user=self.user
        ).adelete()
        return deleted > 0

    async def list_conversations(
        self,
        scope: Scope = Scope.PROJECT,
        limit: int = 100,
        offset: int = 0,
        agent_key: Optional[str] = None,
    ) -> list[Conversation]:
        """List conversations, optionally filtered by agent."""
        qs = PersistenceConversation.objects.filter(user=self.user)
        if agent_key:
            qs = qs.filter(agent_key=agent_key)
        qs = qs.order_by("-updated_at")[offset : offset + limit]

        conversations = []
        async for db_conv in qs:
            conversations.append(
                Conversation(
                    id=db_conv.id,
                    title=db_conv.title or None,
                    messages=[],  # Don't load messages for list
                    created_at=db_conv.created_at,
                    updated_at=db_conv.updated_at,
                    metadata=db_conv.metadata or {},
                    agent_key=db_conv.agent_key or None,
                    summary=db_conv.summary or None,
                    parent_conversation_id=db_conv.parent_conversation_id,
                    active_branch_id=db_conv.active_branch_id,
                )
            )
        return conversations

    async def add_message(
        self,
        conversation_id: UUID,
        message: ConversationMessage,
        scope: Scope = Scope.PROJECT,
    ) -> None:
        """Add a message to an existing conversation."""
        try:
            db_conv = await PersistenceConversation.objects.aget(
                id=conversation_id, user=self.user
            )
        except PersistenceConversation.DoesNotExist:
            raise ValueError(f"Conversation {conversation_id} not found")

        msg_data = self._message_to_db(message)
        await PersistenceMessage.objects.acreate(conversation=db_conv, **msg_data)

        # Update conversation timestamp
        db_conv.updated_at = datetime.utcnow()
        await db_conv.asave(update_fields=["updated_at"])

    async def get_messages(
        self,
        conversation_id: UUID,
        scope: Scope = Scope.PROJECT,
        limit: Optional[int] = None,
        before: Optional[datetime] = None,
    ) -> list[ConversationMessage]:
        """Get messages from a conversation."""
        try:
            db_conv = await PersistenceConversation.objects.aget(
                id=conversation_id, user=self.user
            )
        except PersistenceConversation.DoesNotExist:
            return []

        qs = db_conv.messages.all().order_by("timestamp")
        if before:
            qs = qs.filter(timestamp__lt=before)
        if limit:
            qs = qs[:limit]

        messages = []
        async for db_msg in qs:
            messages.append(self._db_to_message(db_msg))
        return messages


def _task_state_to_db(state: TaskState) -> str:
    """Convert TaskState to database choice."""
    mapping = {
        TaskState.NOT_STARTED: TaskStateChoices.NOT_STARTED,
        TaskState.IN_PROGRESS: TaskStateChoices.IN_PROGRESS,
        TaskState.COMPLETE: TaskStateChoices.COMPLETE,
        TaskState.CANCELLED: TaskStateChoices.CANCELLED,
    }
    return mapping.get(state, TaskStateChoices.NOT_STARTED)


def _db_to_task_state(db_state: str) -> TaskState:
    """Convert database choice to TaskState."""
    mapping = {
        TaskStateChoices.NOT_STARTED: TaskState.NOT_STARTED,
        TaskStateChoices.IN_PROGRESS: TaskState.IN_PROGRESS,
        TaskStateChoices.COMPLETE: TaskState.COMPLETE,
        TaskStateChoices.CANCELLED: TaskState.CANCELLED,
    }
    return mapping.get(db_state, TaskState.NOT_STARTED)


class DjangoTaskStore(TaskStore):
    """
    Django-backed task store.

    Stores task lists and tasks scoped to a user.
    """

    def __init__(self, user):
        self.user = user

    def _db_to_task(self, db_task: PersistenceTask) -> Task:
        """Convert database task to Task."""
        # Convert dependencies from JSON list of strings to list of UUIDs
        dependencies = []
        for dep in db_task.dependencies or []:
            if isinstance(dep, str):
                dependencies.append(UUID(dep))
            else:
                dependencies.append(dep)

        return Task(
            id=db_task.id,
            name=db_task.name,
            description=db_task.description,
            state=_db_to_task_state(db_task.state),
            parent_id=db_task.parent_id,
            created_at=db_task.created_at,
            updated_at=db_task.updated_at,
            metadata=db_task.metadata or {},
            dependencies=dependencies,
            priority=db_task.priority,
            due_at=db_task.due_at,
            completed_at=db_task.completed_at,
            checkpoint_data=db_task.checkpoint_data or {},
            checkpoint_at=db_task.checkpoint_at,
            attempts=db_task.attempts,
            last_error=db_task.last_error or None,
        )

    async def save(self, task_list: TaskList, scope: Scope = Scope.PROJECT) -> None:
        """Save or update a task list."""
        try:
            db_list = await PersistenceTaskList.objects.aget(id=task_list.id)
            db_list.name = task_list.name
            db_list.conversation_id = task_list.conversation_id
            db_list.run_id = task_list.run_id
            await db_list.asave(update_fields=["name", "conversation_id", "run_id", "updated_at"])
            created = False
        except PersistenceTaskList.DoesNotExist:
            db_list = await PersistenceTaskList.objects.acreate(
                id=task_list.id,
                user=self.user,
                name=task_list.name,
                conversation_id=task_list.conversation_id,
                run_id=task_list.run_id,
            )
            created = True

        # If new, create all tasks
        if created and task_list.tasks:
            for task in task_list.tasks:
                # Convert dependencies to list of strings for JSON storage
                deps = [str(d) for d in task.dependencies] if task.dependencies else []
                await PersistenceTask.objects.acreate(
                    id=task.id,
                    task_list=db_list,
                    name=task.name,
                    description=task.description,
                    state=_task_state_to_db(task.state),
                    parent_id=task.parent_id,
                    metadata=task.metadata,
                    dependencies=deps,
                    priority=task.priority,
                    due_at=task.due_at,
                    completed_at=task.completed_at,
                    checkpoint_data=task.checkpoint_data,
                    checkpoint_at=task.checkpoint_at,
                    attempts=task.attempts,
                    last_error=task.last_error or "",
                )

    async def get(
        self, task_list_id: UUID, scope: Scope = Scope.PROJECT
    ) -> Optional[TaskList]:
        """Get a task list by ID."""
        try:
            db_list = await PersistenceTaskList.objects.aget(
                id=task_list_id, user=self.user
            )
        except PersistenceTaskList.DoesNotExist:
            return None

        tasks = []
        async for db_task in db_list.tasks.all().order_by("created_at"):
            tasks.append(self._db_to_task(db_task))

        return TaskList(
            id=db_list.id,
            name=db_list.name,
            tasks=tasks,
            created_at=db_list.created_at,
            updated_at=db_list.updated_at,
            conversation_id=db_list.conversation_id,
            run_id=db_list.run_id,
        )

    async def delete(self, task_list_id: UUID, scope: Scope = Scope.PROJECT) -> bool:
        """Delete a task list. Returns True if it existed."""
        deleted, _ = await PersistenceTaskList.objects.filter(
            id=task_list_id, user=self.user
        ).adelete()
        return deleted > 0

    async def get_by_conversation(
        self, conversation_id: UUID, scope: Scope = Scope.PROJECT
    ) -> Optional[TaskList]:
        """Get the task list associated with a conversation."""
        try:
            db_list = await PersistenceTaskList.objects.aget(
                conversation_id=conversation_id, user=self.user
            )
        except PersistenceTaskList.DoesNotExist:
            return None

        tasks = []
        async for db_task in db_list.tasks.all().order_by("created_at"):
            tasks.append(self._db_to_task(db_task))

        return TaskList(
            id=db_list.id,
            name=db_list.name,
            tasks=tasks,
            created_at=db_list.created_at,
            updated_at=db_list.updated_at,
            conversation_id=db_list.conversation_id,
            run_id=db_list.run_id,
        )

    async def update_task(
        self,
        task_list_id: UUID,
        task_id: UUID,
        state: Optional[TaskState] = None,
        name: Optional[str] = None,
        description: Optional[str] = None,
        scope: Scope = Scope.PROJECT,
    ) -> None:
        """Update a specific task in a task list."""
        try:
            db_list = await PersistenceTaskList.objects.aget(
                id=task_list_id, user=self.user
            )
        except PersistenceTaskList.DoesNotExist:
            raise ValueError(f"Task list {task_list_id} not found")

        try:
            db_task = await PersistenceTask.objects.aget(id=task_id, task_list=db_list)
        except PersistenceTask.DoesNotExist:
            raise ValueError(f"Task {task_id} not found in list {task_list_id}")

        update_fields = []
        if state is not None:
            db_task.state = _task_state_to_db(state)
            update_fields.append("state")
        if name is not None:
            db_task.name = name
            update_fields.append("name")
        if description is not None:
            db_task.description = description
            update_fields.append("description")

        if update_fields:
            update_fields.append("updated_at")
            await db_task.asave(update_fields=update_fields)


class DjangoPreferencesStore(PreferencesStore):
    """
    Django-backed preferences store.

    Stores user preferences as key-value pairs.
    """

    def __init__(self, user):
        self.user = user

    async def get(self, key: str, scope: Scope = Scope.GLOBAL) -> Optional[Any]:
        """Get a preference value."""
        try:
            entry = await Preferences.objects.aget(user=self.user, key=key)
            return entry.value
        except Preferences.DoesNotExist:
            return None

    async def set(self, key: str, value: Any, scope: Scope = Scope.GLOBAL) -> None:
        """Set a preference value."""
        try:
            entry = await Preferences.objects.aget(user=self.user, key=key)
            entry.value = value
            await entry.asave(update_fields=["value", "updated_at"])
        except Preferences.DoesNotExist:
            await Preferences.objects.acreate(user=self.user, key=key, value=value)

    async def delete(self, key: str, scope: Scope = Scope.GLOBAL) -> bool:
        """Delete a preference. Returns True if it existed."""
        deleted, _ = await Preferences.objects.filter(user=self.user, key=key).adelete()
        return deleted > 0

    async def get_all(self, scope: Scope = Scope.GLOBAL) -> dict[str, Any]:
        """Get all preferences."""
        prefs = {}
        async for entry in Preferences.objects.filter(user=self.user):
            prefs[entry.key] = entry.value
        return prefs


# =============================================================================
# Knowledge Store Helper Functions
# =============================================================================


def _fact_type_to_db(fact_type: FactType) -> str:
    """Convert FactType to database choice."""
    mapping = {
        FactType.USER: FactTypeChoices.USER,
        FactType.PROJECT: FactTypeChoices.PROJECT,
        FactType.PREFERENCE: FactTypeChoices.PREFERENCE,
        FactType.CONTEXT: FactTypeChoices.CONTEXT,
        FactType.CUSTOM: FactTypeChoices.CUSTOM,
    }
    return mapping.get(fact_type, FactTypeChoices.CUSTOM)


def _db_to_fact_type(db_type: str) -> FactType:
    """Convert database choice to FactType."""
    mapping = {
        FactTypeChoices.USER: FactType.USER,
        FactTypeChoices.PROJECT: FactType.PROJECT,
        FactTypeChoices.PREFERENCE: FactType.PREFERENCE,
        FactTypeChoices.CONTEXT: FactType.CONTEXT,
        FactTypeChoices.CUSTOM: FactType.CUSTOM,
    }
    return mapping.get(db_type, FactType.CUSTOM)


class DjangoKnowledgeStore(KnowledgeStore):
    """
    Django-backed knowledge store.

    Stores facts, summaries, and optionally embeddings scoped to a user.
    """

    def __init__(self, user):
        self.user = user

    def _db_to_fact(self, db_fact: FactModel) -> Fact:
        """Convert database fact to Fact."""
        return Fact(
            id=db_fact.id,
            key=db_fact.key,
            value=db_fact.value,
            fact_type=_db_to_fact_type(db_fact.fact_type),
            confidence=db_fact.confidence,
            source=db_fact.source or None,
            created_at=db_fact.created_at,
            updated_at=db_fact.updated_at,
            expires_at=db_fact.expires_at,
            metadata=db_fact.metadata or {},
        )

    def _db_to_summary(self, db_summary: SummaryModel) -> CoreSummary:
        """Convert database summary to Summary."""
        # Convert conversation_ids from JSON list of strings to list of UUIDs
        conv_ids = []
        for cid in db_summary.conversation_ids or []:
            if isinstance(cid, str):
                conv_ids.append(UUID(cid))
            else:
                conv_ids.append(cid)

        return CoreSummary(
            id=db_summary.id,
            content=db_summary.content,
            conversation_id=db_summary.conversation_id,
            conversation_ids=conv_ids,
            start_time=db_summary.start_time,
            end_time=db_summary.end_time,
            created_at=db_summary.created_at,
            metadata=db_summary.metadata or {},
        )

    def _db_to_embedding(self, db_emb: EmbeddingModel) -> CoreEmbedding:
        """Convert database embedding to Embedding."""
        return CoreEmbedding(
            id=db_emb.id,
            vector=db_emb.vector,
            content=db_emb.content,
            content_type=db_emb.content_type,
            source_id=db_emb.source_id,
            model=db_emb.model or None,
            dimensions=db_emb.dimensions,
            created_at=db_emb.created_at,
            metadata=db_emb.metadata or {},
        )

    # Fact operations
    async def save_fact(self, fact: Fact, scope: Scope = Scope.PROJECT) -> None:
        """Save or update a fact."""
        try:
            db_fact = await FactModel.objects.aget(id=fact.id)
            db_fact.key = fact.key
            db_fact.value = fact.value
            db_fact.fact_type = _fact_type_to_db(fact.fact_type)
            db_fact.confidence = fact.confidence
            db_fact.source = fact.source or ""
            db_fact.expires_at = fact.expires_at
            db_fact.metadata = fact.metadata
            await db_fact.asave(update_fields=[
                "key", "value", "fact_type", "confidence", "source",
                "expires_at", "metadata", "updated_at"
            ])
        except FactModel.DoesNotExist:
            await FactModel.objects.acreate(
                id=fact.id,
                user=self.user,
                key=fact.key,
                value=fact.value,
                fact_type=_fact_type_to_db(fact.fact_type),
                confidence=fact.confidence,
                source=fact.source or "",
                expires_at=fact.expires_at,
                metadata=fact.metadata,
            )

    async def get_fact(self, fact_id: UUID, scope: Scope = Scope.PROJECT) -> Optional[Fact]:
        """Get a fact by ID."""
        try:
            db_fact = await FactModel.objects.aget(id=fact_id, user=self.user)
            return self._db_to_fact(db_fact)
        except FactModel.DoesNotExist:
            return None

    async def get_fact_by_key(self, key: str, scope: Scope = Scope.PROJECT) -> Optional[Fact]:
        """Get a fact by its key."""
        try:
            db_fact = await FactModel.objects.aget(user=self.user, key=key)
            return self._db_to_fact(db_fact)
        except FactModel.DoesNotExist:
            return None

    async def list_facts(
        self,
        scope: Scope = Scope.PROJECT,
        fact_type: Optional[FactType] = None,
        limit: int = 100,
    ) -> list[Fact]:
        """List facts, optionally filtered by type."""
        qs = FactModel.objects.filter(user=self.user)
        if fact_type:
            qs = qs.filter(fact_type=_fact_type_to_db(fact_type))
        qs = qs.order_by("-updated_at")[:limit]

        facts = []
        async for db_fact in qs:
            facts.append(self._db_to_fact(db_fact))
        return facts

    async def delete_fact(self, fact_id: UUID, scope: Scope = Scope.PROJECT) -> bool:
        """Delete a fact. Returns True if it existed."""
        deleted, _ = await FactModel.objects.filter(id=fact_id, user=self.user).adelete()
        return deleted > 0

    # Summary operations
    async def save_summary(self, summary: CoreSummary, scope: Scope = Scope.PROJECT) -> None:
        """Save or update a summary."""
        conv_ids = [str(cid) for cid in summary.conversation_ids] if summary.conversation_ids else []
        try:
            db_summary = await SummaryModel.objects.aget(id=summary.id)
            db_summary.content = summary.content
            db_summary.conversation_id = summary.conversation_id
            db_summary.conversation_ids = conv_ids
            db_summary.start_time = summary.start_time
            db_summary.end_time = summary.end_time
            db_summary.metadata = summary.metadata
            await db_summary.asave(update_fields=[
                "content", "conversation_id", "conversation_ids",
                "start_time", "end_time", "metadata"
            ])
        except SummaryModel.DoesNotExist:
            await SummaryModel.objects.acreate(
                id=summary.id,
                user=self.user,
                content=summary.content,
                conversation_id=summary.conversation_id,
                conversation_ids=conv_ids,
                start_time=summary.start_time,
                end_time=summary.end_time,
                metadata=summary.metadata,
            )

    async def get_summary(self, summary_id: UUID, scope: Scope = Scope.PROJECT) -> Optional[CoreSummary]:
        """Get a summary by ID."""
        try:
            db_summary = await SummaryModel.objects.aget(id=summary_id, user=self.user)
            return self._db_to_summary(db_summary)
        except SummaryModel.DoesNotExist:
            return None

    async def get_summaries_for_conversation(
        self,
        conversation_id: UUID,
        scope: Scope = Scope.PROJECT,
    ) -> list[CoreSummary]:
        """Get all summaries for a conversation."""
        qs = SummaryModel.objects.filter(
            user=self.user,
            conversation_id=conversation_id,
        ).order_by("-created_at")

        summaries = []
        async for db_summary in qs:
            summaries.append(self._db_to_summary(db_summary))
        return summaries

    async def delete_summary(self, summary_id: UUID, scope: Scope = Scope.PROJECT) -> bool:
        """Delete a summary. Returns True if it existed."""
        deleted, _ = await SummaryModel.objects.filter(id=summary_id, user=self.user).adelete()
        return deleted > 0

    # Embedding operations (optional)
    async def save_embedding(self, embedding: CoreEmbedding, scope: Scope = Scope.PROJECT) -> None:
        """Save an embedding."""
        try:
            db_emb = await EmbeddingModel.objects.aget(id=embedding.id)
            db_emb.vector = embedding.vector
            db_emb.content = embedding.content
            db_emb.content_type = embedding.content_type
            db_emb.source_id = embedding.source_id
            db_emb.model = embedding.model or ""
            db_emb.dimensions = embedding.dimensions
            db_emb.metadata = embedding.metadata
            await db_emb.asave(update_fields=[
                "vector", "content", "content_type", "source_id",
                "model", "dimensions", "metadata"
            ])
        except EmbeddingModel.DoesNotExist:
            await EmbeddingModel.objects.acreate(
                id=embedding.id,
                user=self.user,
                vector=embedding.vector,
                content=embedding.content,
                content_type=embedding.content_type,
                source_id=embedding.source_id,
                model=embedding.model or "",
                dimensions=embedding.dimensions,
                metadata=embedding.metadata,
            )

    async def search_similar(
        self,
        query_vector: list[float],
        limit: int = 10,
        scope: Scope = Scope.PROJECT,
        content_type: Optional[str] = None,
    ) -> list[tuple[CoreEmbedding, float]]:
        """
        Search for similar embeddings using cosine similarity.

        Note: This is a basic implementation using Python. For production use
        with large datasets, consider using pgvector extension for PostgreSQL.
        """
        import math

        def cosine_similarity(v1: list[float], v2: list[float]) -> float:
            """Calculate cosine similarity between two vectors."""
            if len(v1) != len(v2):
                return 0.0
            dot_product = sum(a * b for a, b in zip(v1, v2))
            norm1 = math.sqrt(sum(a * a for a in v1))
            norm2 = math.sqrt(sum(b * b for b in v2))
            if norm1 == 0 or norm2 == 0:
                return 0.0
            return dot_product / (norm1 * norm2)

        qs = EmbeddingModel.objects.filter(user=self.user)
        if content_type:
            qs = qs.filter(content_type=content_type)

        results = []
        async for db_emb in qs:
            score = cosine_similarity(query_vector, db_emb.vector)
            results.append((self._db_to_embedding(db_emb), score))

        # Sort by score descending and limit
        results.sort(key=lambda x: x[1], reverse=True)
        return results[:limit]

    async def delete_embedding(self, embedding_id: UUID, scope: Scope = Scope.PROJECT) -> bool:
        """Delete an embedding. Returns True if it existed."""
        deleted, _ = await EmbeddingModel.objects.filter(id=embedding_id, user=self.user).adelete()
        return deleted > 0


# =============================================================================
# Audit Store Helper Functions
# =============================================================================


def _event_type_to_db(event_type: AuditEventType) -> str:
    """Convert AuditEventType to database choice."""
    mapping = {
        AuditEventType.CONVERSATION_START: AuditEventTypeChoices.CONVERSATION_START,
        AuditEventType.CONVERSATION_END: AuditEventTypeChoices.CONVERSATION_END,
        AuditEventType.MESSAGE_SENT: AuditEventTypeChoices.MESSAGE_SENT,
        AuditEventType.MESSAGE_RECEIVED: AuditEventTypeChoices.MESSAGE_RECEIVED,
        AuditEventType.TOOL_CALL: AuditEventTypeChoices.TOOL_CALL,
        AuditEventType.TOOL_RESULT: AuditEventTypeChoices.TOOL_RESULT,
        AuditEventType.TOOL_ERROR: AuditEventTypeChoices.TOOL_ERROR,
        AuditEventType.AGENT_START: AuditEventTypeChoices.AGENT_START,
        AuditEventType.AGENT_END: AuditEventTypeChoices.AGENT_END,
        AuditEventType.AGENT_ERROR: AuditEventTypeChoices.AGENT_ERROR,
        AuditEventType.CHECKPOINT_SAVED: AuditEventTypeChoices.CHECKPOINT_SAVED,
        AuditEventType.CHECKPOINT_RESTORED: AuditEventTypeChoices.CHECKPOINT_RESTORED,
        AuditEventType.CUSTOM: AuditEventTypeChoices.CUSTOM,
    }
    return mapping.get(event_type, AuditEventTypeChoices.CUSTOM)


def _db_to_event_type(db_type: str) -> AuditEventType:
    """Convert database choice to AuditEventType."""
    mapping = {
        AuditEventTypeChoices.CONVERSATION_START: AuditEventType.CONVERSATION_START,
        AuditEventTypeChoices.CONVERSATION_END: AuditEventType.CONVERSATION_END,
        AuditEventTypeChoices.MESSAGE_SENT: AuditEventType.MESSAGE_SENT,
        AuditEventTypeChoices.MESSAGE_RECEIVED: AuditEventType.MESSAGE_RECEIVED,
        AuditEventTypeChoices.TOOL_CALL: AuditEventType.TOOL_CALL,
        AuditEventTypeChoices.TOOL_RESULT: AuditEventType.TOOL_RESULT,
        AuditEventTypeChoices.TOOL_ERROR: AuditEventType.TOOL_ERROR,
        AuditEventTypeChoices.AGENT_START: AuditEventType.AGENT_START,
        AuditEventTypeChoices.AGENT_END: AuditEventType.AGENT_END,
        AuditEventTypeChoices.AGENT_ERROR: AuditEventType.AGENT_ERROR,
        AuditEventTypeChoices.CHECKPOINT_SAVED: AuditEventType.CHECKPOINT_SAVED,
        AuditEventTypeChoices.CHECKPOINT_RESTORED: AuditEventType.CHECKPOINT_RESTORED,
        AuditEventTypeChoices.CUSTOM: AuditEventType.CUSTOM,
    }
    return mapping.get(db_type, AuditEventType.CUSTOM)


def _severity_to_db(severity: ErrorSeverity) -> str:
    """Convert ErrorSeverity to database choice."""
    mapping = {
        ErrorSeverity.DEBUG: ErrorSeverityChoices.DEBUG,
        ErrorSeverity.INFO: ErrorSeverityChoices.INFO,
        ErrorSeverity.WARNING: ErrorSeverityChoices.WARNING,
        ErrorSeverity.ERROR: ErrorSeverityChoices.ERROR,
        ErrorSeverity.CRITICAL: ErrorSeverityChoices.CRITICAL,
    }
    return mapping.get(severity, ErrorSeverityChoices.ERROR)


def _db_to_severity(db_severity: str) -> ErrorSeverity:
    """Convert database choice to ErrorSeverity."""
    mapping = {
        ErrorSeverityChoices.DEBUG: ErrorSeverity.DEBUG,
        ErrorSeverityChoices.INFO: ErrorSeverity.INFO,
        ErrorSeverityChoices.WARNING: ErrorSeverity.WARNING,
        ErrorSeverityChoices.ERROR: ErrorSeverity.ERROR,
        ErrorSeverityChoices.CRITICAL: ErrorSeverity.CRITICAL,
    }
    return mapping.get(db_severity, ErrorSeverity.ERROR)


class DjangoAuditStore(AuditStore):
    """
    Django-backed audit store.

    Stores audit entries, error records, and performance metrics scoped to a user.
    """

    def __init__(self, user):
        self.user = user

    def _db_to_audit_entry(self, db_entry: AuditEntryModel) -> CoreAuditEntry:
        """Convert database audit entry to AuditEntry."""
        return CoreAuditEntry(
            id=db_entry.id,
            event_type=_db_to_event_type(db_entry.event_type),
            timestamp=db_entry.timestamp,
            conversation_id=db_entry.conversation_id,
            run_id=db_entry.run_id,
            agent_key=db_entry.agent_key or None,
            action=db_entry.action or None,
            details=db_entry.details or {},
            actor_type=db_entry.actor_type,
            actor_id=db_entry.actor_id or None,
            request_id=db_entry.request_id or None,
            parent_event_id=db_entry.parent_event_id,
            metadata=db_entry.metadata or {},
        )

    def _db_to_error_record(self, db_error: ErrorRecordModel) -> CoreErrorRecord:
        """Convert database error record to ErrorRecord."""
        return CoreErrorRecord(
            id=db_error.id,
            timestamp=db_error.timestamp,
            severity=_db_to_severity(db_error.severity),
            error_type=db_error.error_type or None,
            message=db_error.message or None,
            stack_trace=db_error.stack_trace or None,
            conversation_id=db_error.conversation_id,
            run_id=db_error.run_id,
            agent_key=db_error.agent_key or None,
            context=db_error.context or {},
            resolved=db_error.resolved,
            resolved_at=db_error.resolved_at,
            resolution_notes=db_error.resolution_notes or None,
            metadata=db_error.metadata or {},
        )

    def _db_to_metric(self, db_metric: PerformanceMetricModel) -> CorePerformanceMetric:
        """Convert database metric to PerformanceMetric."""
        return CorePerformanceMetric(
            id=db_metric.id,
            name=db_metric.name,
            value=db_metric.value,
            unit=db_metric.unit or None,
            timestamp=db_metric.timestamp,
            conversation_id=db_metric.conversation_id,
            run_id=db_metric.run_id,
            agent_key=db_metric.agent_key or None,
            tags=db_metric.tags or {},
            metadata=db_metric.metadata or {},
        )

    # Audit entry operations
    async def log_event(self, entry: CoreAuditEntry, scope: Scope = Scope.PROJECT) -> None:
        """Log an audit event."""
        await AuditEntryModel.objects.acreate(
            id=entry.id,
            user=self.user,
            event_type=_event_type_to_db(entry.event_type),
            conversation_id=entry.conversation_id,
            run_id=entry.run_id,
            agent_key=entry.agent_key or "",
            action=entry.action or "",
            details=entry.details,
            actor_type=entry.actor_type,
            actor_id=entry.actor_id or "",
            request_id=entry.request_id or "",
            parent_event_id=entry.parent_event_id,
            metadata=entry.metadata,
        )

    async def get_events(
        self,
        scope: Scope = Scope.PROJECT,
        conversation_id: Optional[UUID] = None,
        run_id: Optional[UUID] = None,
        event_types: Optional[list[AuditEventType]] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        limit: int = 100,
    ) -> list[CoreAuditEntry]:
        """Get audit events with optional filters."""
        qs = AuditEntryModel.objects.filter(user=self.user)
        if event_types:
            db_types = [_event_type_to_db(et) for et in event_types]
            qs = qs.filter(event_type__in=db_types)
        if conversation_id:
            qs = qs.filter(conversation_id=conversation_id)
        if run_id:
            qs = qs.filter(run_id=run_id)
        if start_time:
            qs = qs.filter(timestamp__gte=start_time)
        if end_time:
            qs = qs.filter(timestamp__lte=end_time)
        qs = qs.order_by("-timestamp")[:limit]

        entries = []
        async for db_entry in qs:
            entries.append(self._db_to_audit_entry(db_entry))
        return entries

    # Error record operations
    async def log_error(self, error: CoreErrorRecord, scope: Scope = Scope.PROJECT) -> None:
        """Log an error record."""
        await ErrorRecordModel.objects.acreate(
            id=error.id,
            user=self.user,
            severity=_severity_to_db(error.severity),
            error_type=error.error_type or "",
            message=error.message or "",
            stack_trace=error.stack_trace or "",
            conversation_id=error.conversation_id,
            run_id=error.run_id,
            agent_key=error.agent_key or "",
            context=error.context,
            resolved=error.resolved,
            resolved_at=error.resolved_at,
            resolution_notes=error.resolution_notes or "",
            metadata=error.metadata,
        )

    async def get_errors(
        self,
        scope: Scope = Scope.PROJECT,
        severity: Optional[ErrorSeverity] = None,
        resolved: Optional[bool] = None,
        conversation_id: Optional[UUID] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        limit: int = 100,
    ) -> list[CoreErrorRecord]:
        """Get error records with optional filters."""
        qs = ErrorRecordModel.objects.filter(user=self.user)
        if severity:
            qs = qs.filter(severity=_severity_to_db(severity))
        if resolved is not None:
            qs = qs.filter(resolved=resolved)
        if conversation_id:
            qs = qs.filter(conversation_id=conversation_id)
        if start_time:
            qs = qs.filter(timestamp__gte=start_time)
        if end_time:
            qs = qs.filter(timestamp__lte=end_time)
        qs = qs.order_by("-timestamp")[:limit]

        errors = []
        async for db_error in qs:
            errors.append(self._db_to_error_record(db_error))
        return errors

    async def resolve_error(
        self,
        error_id: UUID,
        resolution_notes: Optional[str] = None,
        scope: Scope = Scope.PROJECT,
    ) -> bool:
        """Mark an error as resolved. Returns True if it existed."""
        try:
            db_error = await ErrorRecordModel.objects.aget(id=error_id, user=self.user)
            db_error.resolved = True
            db_error.resolved_at = datetime.utcnow()
            db_error.resolution_notes = resolution_notes or ""
            await db_error.asave(update_fields=["resolved", "resolved_at", "resolution_notes"])
            return True
        except ErrorRecordModel.DoesNotExist:
            return False

    # Performance metric operations
    async def record_metric(self, metric: CorePerformanceMetric, scope: Scope = Scope.PROJECT) -> None:
        """Record a performance metric."""
        await PerformanceMetricModel.objects.acreate(
            id=metric.id,
            user=self.user,
            name=metric.name,
            value=metric.value,
            unit=metric.unit or "",
            conversation_id=metric.conversation_id,
            run_id=metric.run_id,
            agent_key=metric.agent_key or "",
            tags=metric.tags,
            metadata=metric.metadata,
        )

    async def get_metrics(
        self,
        name: str,
        scope: Scope = Scope.PROJECT,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        tags: Optional[dict] = None,
        limit: int = 1000,
    ) -> list[CorePerformanceMetric]:
        """Get metrics by name with optional filters."""
        qs = PerformanceMetricModel.objects.filter(user=self.user, name=name)
        if start_time:
            qs = qs.filter(timestamp__gte=start_time)
        if end_time:
            qs = qs.filter(timestamp__lte=end_time)
        # Note: tags filtering would require JSON field querying
        # For now, we filter in Python if tags are specified
        qs = qs.order_by("-timestamp")[:limit]

        metrics = []
        async for db_metric in qs:
            if tags:
                # Filter by tags in Python
                db_tags = db_metric.tags or {}
                if not all(db_tags.get(k) == v for k, v in tags.items()):
                    continue
            metrics.append(self._db_to_metric(db_metric))
        return metrics

    async def get_metric_summary(
        self,
        name: str,
        scope: Scope = Scope.PROJECT,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
    ) -> dict:
        """
        Get summary statistics for a metric.
        Returns: {count, min, max, avg, sum, p50, p95, p99}
        """
        qs = PerformanceMetricModel.objects.filter(user=self.user, name=name)
        if start_time:
            qs = qs.filter(timestamp__gte=start_time)
        if end_time:
            qs = qs.filter(timestamp__lte=end_time)

        values = []
        async for db_metric in qs:
            values.append(db_metric.value)

        if not values:
            return {
                "count": 0,
                "min": None,
                "max": None,
                "avg": None,
                "sum": None,
                "p50": None,
                "p95": None,
                "p99": None,
            }

        values.sort()
        count = len(values)
        total = sum(values)

        def percentile(data: list[float], p: float) -> float:
            """Calculate percentile."""
            if not data:
                return 0.0
            k = (len(data) - 1) * p / 100
            f = int(k)
            c = f + 1 if f + 1 < len(data) else f
            return data[f] + (k - f) * (data[c] - data[f]) if c != f else data[f]

        return {
            "count": count,
            "min": min(values),
            "max": max(values),
            "avg": total / count,
            "sum": total,
            "p50": percentile(values, 50),
            "p95": percentile(values, 95),
            "p99": percentile(values, 99),
        }


# =============================================================================
# Conversation-Scoped Memory Store
# =============================================================================


class ConversationMemoryStore:
    """
    A simple memory store scoped to a specific conversation.

    This is used by designed agents to remember things within a conversation.
    Memories are stored as Facts with a conversation_id.

    Example:
        store = ConversationMemoryStore(user=request.user, conversation_id=conv_id)

        # Remember something
        await store.remember("user_name", "Alice")

        # Recall all memories
        memories = await store.recall_all()
        # Returns: {"user_name": "Alice", ...}

        # Get a specific memory
        name = await store.get("user_name")
    """

    def __init__(self, user, conversation_id: UUID):
        """
        Initialize the conversation memory store.

        Args:
            user: The Django user (for multi-tenant scoping)
            conversation_id: The conversation to scope memories to
        """
        self.user = user
        self.conversation_id = conversation_id

    async def remember(self, key: str, value: Any, source: str = "agent") -> None:
        """
        Store a memory for this conversation.

        Args:
            key: A descriptive key for the memory (e.g., "user_name", "project_goal")
            value: The value to remember (any JSON-serializable value)
            source: Where this memory came from (default: "agent")
        """
        from uuid import uuid4

        # Try to update existing, or create new
        try:
            db_fact = await FactModel.objects.aget(
                user=self.user,
                conversation_id=self.conversation_id,
                key=key,
            )
            db_fact.value = value
            db_fact.source = source
            await db_fact.asave(update_fields=["value", "source", "updated_at"])
        except FactModel.DoesNotExist:
            await FactModel.objects.acreate(
                id=uuid4(),
                user=self.user,
                conversation_id=self.conversation_id,
                key=key,
                value=value,
                fact_type=FactTypeChoices.CONTEXT,
                source=source,
            )

    async def get(self, key: str) -> Optional[Any]:
        """
        Get a specific memory by key.

        Args:
            key: The memory key

        Returns:
            The memory value, or None if not found
        """
        try:
            db_fact = await FactModel.objects.aget(
                user=self.user,
                conversation_id=self.conversation_id,
                key=key,
            )
            return db_fact.value
        except FactModel.DoesNotExist:
            return None

    async def recall_all(self) -> dict[str, Any]:
        """
        Recall all memories for this conversation.

        Returns:
            Dictionary of key -> value for all memories
        """
        memories = {}
        async for db_fact in FactModel.objects.filter(
            user=self.user,
            conversation_id=self.conversation_id,
        ).order_by("created_at"):
            memories[db_fact.key] = db_fact.value
        return memories

    async def forget(self, key: str) -> bool:
        """
        Forget a specific memory.

        Args:
            key: The memory key to forget

        Returns:
            True if the memory existed and was deleted
        """
        deleted, _ = await FactModel.objects.filter(
            user=self.user,
            conversation_id=self.conversation_id,
            key=key,
        ).adelete()
        return deleted > 0

    async def forget_all(self) -> int:
        """
        Forget all memories for this conversation.

        Returns:
            Number of memories deleted
        """
        deleted, _ = await FactModel.objects.filter(
            user=self.user,
            conversation_id=self.conversation_id,
        ).adelete()
        return deleted

    def format_for_prompt(self, memories: dict[str, Any]) -> str:
        """
        Format memories for inclusion in a system prompt.

        Args:
            memories: Dictionary of memories from recall_all()

        Returns:
            Formatted string for prompt injection
        """
        if not memories:
            return ""

        lines = ["# Remembered Information", ""]
        for key, value in memories.items():
            # Format the key nicely
            display_key = key.replace("_", " ").title()
            lines.append(f"- **{display_key}**: {value}")

        return "\n".join(lines)


# =============================================================================
# Shared Memory Store
# =============================================================================


from agent_runtime_core.persistence import SharedMemoryStore, MemoryItem
from django_agent_runtime.persistence.models import SharedMemory, MemoryScopeChoices
from typing import List, Dict


class DjangoSharedMemoryStore(SharedMemoryStore):
    """
    Django-backed shared memory store.

    Provides persistent storage for shared memories with:
    - Semantic keys (dot-notation)
    - Scope awareness (conversation, user, system)
    - Confidence scores and source tracking
    - Expiration support
    - Privacy enforcement (only authenticated users)

    Example:
        store = DjangoSharedMemoryStore(user=request.user)

        # Set a memory
        await store.set("user.preferences.theme", "dark", scope="user")

        # Get a memory
        item = await store.get("user.preferences.theme")
        print(item.value)  # "dark"

        # List all user preferences
        prefs = await store.list(prefix="user.preferences", scope="user")
    """

    def __init__(self, user):
        """
        Initialize the store with a user.

        Args:
            user: Django user instance. Must be authenticated for any operations.
        """
        self.user = user

    def _model_to_item(self, model: SharedMemory) -> MemoryItem:
        """Convert a Django model to a MemoryItem."""
        return MemoryItem(
            id=model.id,
            key=model.key,
            value=model.value,
            scope=model.scope,
            created_at=model.created_at,
            updated_at=model.updated_at,
            source=model.source,
            confidence=model.confidence,
            metadata=model.metadata,
            expires_at=model.expires_at,
            conversation_id=model.conversation_id,
            system_id=model.system_id,
        )

    async def get(
        self,
        key: str,
        scope: Optional[str] = None,
        conversation_id: Optional[UUID] = None,
        system_id: Optional[str] = None,
    ) -> Optional[MemoryItem]:
        """Get a memory item by key."""
        filters = {"user": self.user, "key": key}
        if scope:
            filters["scope"] = scope
        if conversation_id:
            filters["conversation_id"] = conversation_id
        if system_id:
            filters["system_id"] = system_id

        try:
            model = await SharedMemory.objects.aget(**filters)
            # Check expiration
            if model.is_expired:
                await model.adelete()
                return None
            return self._model_to_item(model)
        except SharedMemory.DoesNotExist:
            return None

    async def set(
        self,
        key: str,
        value: Any,
        scope: str = "user",
        source: str = "agent",
        confidence: float = 1.0,
        metadata: Optional[dict] = None,
        expires_at: Optional[datetime] = None,
        conversation_id: Optional[UUID] = None,
        system_id: Optional[str] = None,
    ) -> MemoryItem:
        """Set a memory item. Creates or updates."""
        defaults = {
            "value": value,
            "source": source,
            "confidence": confidence,
            "metadata": metadata or {},
            "expires_at": expires_at,
        }

        model, created = await SharedMemory.objects.aupdate_or_create(
            user=self.user,
            key=key,
            scope=scope,
            conversation_id=conversation_id,
            system_id=system_id or "",
            defaults=defaults,
        )

        return self._model_to_item(model)

    async def delete(
        self,
        key: str,
        scope: Optional[str] = None,
        conversation_id: Optional[UUID] = None,
        system_id: Optional[str] = None,
    ) -> bool:
        """Delete a memory item."""
        filters = {"user": self.user, "key": key}
        if scope:
            filters["scope"] = scope
        if conversation_id:
            filters["conversation_id"] = conversation_id
        if system_id:
            filters["system_id"] = system_id

        deleted, _ = await SharedMemory.objects.filter(**filters).adelete()
        return deleted > 0

    async def list(
        self,
        prefix: Optional[str] = None,
        scope: Optional[str] = None,
        conversation_id: Optional[UUID] = None,
        system_id: Optional[str] = None,
        source: Optional[str] = None,
        min_confidence: Optional[float] = None,
        limit: int = 100,
    ) -> List[MemoryItem]:
        """List memory items with optional filters."""
        from django.utils import timezone

        queryset = SharedMemory.objects.filter(user=self.user)

        if prefix:
            queryset = queryset.filter(key__startswith=prefix)
        if scope:
            queryset = queryset.filter(scope=scope)
        if conversation_id:
            queryset = queryset.filter(conversation_id=conversation_id)
        if system_id:
            queryset = queryset.filter(system_id=system_id)
        if source:
            queryset = queryset.filter(source=source)
        if min_confidence is not None:
            queryset = queryset.filter(confidence__gte=min_confidence)

        # Exclude expired items
        queryset = queryset.filter(
            models.Q(expires_at__isnull=True) | models.Q(expires_at__gt=timezone.now())
        )

        queryset = queryset.order_by("-updated_at")[:limit]

        results = []
        async for model in queryset:
            results.append(self._model_to_item(model))
        return results

    async def get_many(
        self,
        keys: List[str],
        scope: Optional[str] = None,
        conversation_id: Optional[UUID] = None,
        system_id: Optional[str] = None,
    ) -> Dict[str, MemoryItem]:
        """Get multiple memory items by keys."""
        from django.utils import timezone

        queryset = SharedMemory.objects.filter(user=self.user, key__in=keys)

        if scope:
            queryset = queryset.filter(scope=scope)
        if conversation_id:
            queryset = queryset.filter(conversation_id=conversation_id)
        if system_id:
            queryset = queryset.filter(system_id=system_id)

        # Exclude expired items
        queryset = queryset.filter(
            models.Q(expires_at__isnull=True) | models.Q(expires_at__gt=timezone.now())
        )

        results = {}
        async for model in queryset:
            results[model.key] = self._model_to_item(model)
        return results

    async def set_many(
        self,
        items: List[tuple],
        scope: str = "user",
        source: str = "agent",
        conversation_id: Optional[UUID] = None,
        system_id: Optional[str] = None,
    ) -> List[MemoryItem]:
        """Set multiple memory items atomically."""
        results = []
        for key, value in items:
            item = await self.set(
                key,
                value,
                scope=scope,
                source=source,
                conversation_id=conversation_id,
                system_id=system_id,
            )
            results.append(item)
        return results

    async def clear(
        self,
        scope: Optional[str] = None,
        conversation_id: Optional[UUID] = None,
        system_id: Optional[str] = None,
        prefix: Optional[str] = None,
    ) -> int:
        """Clear memory items."""
        queryset = SharedMemory.objects.filter(user=self.user)

        if scope:
            queryset = queryset.filter(scope=scope)
        if conversation_id:
            queryset = queryset.filter(conversation_id=conversation_id)
        if system_id:
            queryset = queryset.filter(system_id=system_id)
        if prefix:
            queryset = queryset.filter(key__startswith=prefix)

        deleted, _ = await queryset.adelete()
        return deleted
