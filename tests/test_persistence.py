"""
Tests for the Django persistence stores.

Note: Async tests require PostgreSQL due to SQLite locking issues.
Run with: USE_POSTGRES_FOR_TESTS=1 pytest tests/test_persistence.py
"""

import pytest
from uuid import uuid4
from datetime import datetime

from django.conf import settings
from django.contrib.auth import get_user_model

# Skip async tests on SQLite due to locking issues
requires_postgres = pytest.mark.skipif(
    settings.DATABASES["default"]["ENGINE"] == "django.db.backends.sqlite3",
    reason="Async tests require PostgreSQL (SQLite has locking issues)"
)

from agent_runtime_core.persistence import (
    Conversation,
    ConversationMessage,
    Task,
    TaskList,
    TaskState,
    Scope,
)

from django_agent_runtime.persistence import (
    DjangoMemoryStore,
    DjangoConversationStore,
    DjangoTaskStore,
    DjangoPreferencesStore,
    get_persistence_manager,
    get_persistence_config,
)
from django_agent_runtime.persistence.models import (
    Memory,
    PersistenceConversation,
    PersistenceMessage,
    PersistenceTaskList,
    PersistenceTask,
    Preferences,
)


User = get_user_model()


@pytest.fixture
def user(db):
    """Create a test user."""
    return User.objects.create_user(
        username="testuser",
        email="test@example.com",
        password="testpass123",
    )


@pytest.fixture
def other_user(db):
    """Create another test user for isolation tests."""
    return User.objects.create_user(
        username="otheruser",
        email="other@example.com",
        password="testpass123",
    )


@requires_postgres
@pytest.mark.django_db(transaction=True)
class TestDjangoMemoryStore:
    """Tests for DjangoMemoryStore."""

    @pytest.mark.asyncio
    async def test_set_and_get(self, user):
        """Test setting and getting a value."""
        store = DjangoMemoryStore(user=user)
        
        await store.set("test_key", {"foo": "bar"})
        value = await store.get("test_key")
        
        assert value == {"foo": "bar"}

    @pytest.mark.asyncio
    async def test_get_nonexistent(self, user):
        """Test getting a nonexistent key returns None."""
        store = DjangoMemoryStore(user=user)
        
        value = await store.get("nonexistent")
        
        assert value is None

    @pytest.mark.asyncio
    async def test_delete(self, user):
        """Test deleting a key."""
        store = DjangoMemoryStore(user=user)
        
        await store.set("to_delete", "value")
        deleted = await store.delete("to_delete")
        
        assert deleted is True
        assert await store.get("to_delete") is None

    @pytest.mark.asyncio
    async def test_delete_nonexistent(self, user):
        """Test deleting a nonexistent key returns False."""
        store = DjangoMemoryStore(user=user)
        
        deleted = await store.delete("nonexistent")
        
        assert deleted is False

    @pytest.mark.asyncio
    async def test_list_keys(self, user):
        """Test listing keys."""
        store = DjangoMemoryStore(user=user)
        
        await store.set("key1", "value1")
        await store.set("key2", "value2")
        await store.set("other", "value3")
        
        keys = await store.list_keys()
        
        assert set(keys) == {"key1", "key2", "other"}

    @pytest.mark.asyncio
    async def test_list_keys_with_prefix(self, user):
        """Test listing keys with prefix filter."""
        store = DjangoMemoryStore(user=user)
        
        await store.set("prefix_a", "value1")
        await store.set("prefix_b", "value2")
        await store.set("other", "value3")
        
        keys = await store.list_keys(prefix="prefix_")
        
        assert set(keys) == {"prefix_a", "prefix_b"}

    @pytest.mark.asyncio
    async def test_clear(self, user):
        """Test clearing all keys."""
        store = DjangoMemoryStore(user=user)
        
        await store.set("key1", "value1")
        await store.set("key2", "value2")
        await store.clear()
        
        keys = await store.list_keys()
        
        assert keys == []

    @pytest.mark.asyncio
    async def test_user_isolation(self, user, other_user):
        """Test that users can't see each other's data."""
        store1 = DjangoMemoryStore(user=user)
        store2 = DjangoMemoryStore(user=other_user)
        
        await store1.set("shared_key", "user1_value")
        await store2.set("shared_key", "user2_value")
        
        assert await store1.get("shared_key") == "user1_value"
        assert await store2.get("shared_key") == "user2_value"


@requires_postgres
@pytest.mark.django_db(transaction=True)
class TestDjangoPreferencesStore:
    """Tests for DjangoPreferencesStore."""

    @pytest.mark.asyncio
    async def test_set_and_get(self, user):
        """Test setting and getting a preference."""
        store = DjangoPreferencesStore(user=user)

        await store.set("theme", "dark")
        value = await store.get("theme")

        assert value == "dark"

    @pytest.mark.asyncio
    async def test_get_all(self, user):
        """Test getting all preferences."""
        store = DjangoPreferencesStore(user=user)

        await store.set("theme", "dark")
        await store.set("language", "en")

        prefs = await store.get_all()

        assert prefs == {"theme": "dark", "language": "en"}

    @pytest.mark.asyncio
    async def test_delete(self, user):
        """Test deleting a preference."""
        store = DjangoPreferencesStore(user=user)

        await store.set("to_delete", "value")
        deleted = await store.delete("to_delete")

        assert deleted is True
        assert await store.get("to_delete") is None


@requires_postgres
@pytest.mark.django_db(transaction=True)
class TestDjangoConversationStore:
    """Tests for DjangoConversationStore."""

    @pytest.mark.asyncio
    async def test_save_and_get(self, user):
        """Test saving and getting a conversation."""
        store = DjangoConversationStore(user=user)

        conv_id = uuid4()
        conv = Conversation(
            id=conv_id,
            title="Test Conversation",
            agent_key="test-agent",
            metadata={"key": "value"},
        )

        await store.save(conv)
        retrieved = await store.get(conv_id)

        assert retrieved is not None
        assert retrieved.id == conv_id
        assert retrieved.title == "Test Conversation"
        assert retrieved.agent_key == "test-agent"

    @pytest.mark.asyncio
    async def test_get_nonexistent(self, user):
        """Test getting a nonexistent conversation returns None."""
        store = DjangoConversationStore(user=user)

        result = await store.get(uuid4())

        assert result is None

    @pytest.mark.asyncio
    async def test_delete(self, user):
        """Test deleting a conversation."""
        store = DjangoConversationStore(user=user)

        conv_id = uuid4()
        conv = Conversation(id=conv_id, title="To Delete")
        await store.save(conv)

        deleted = await store.delete(conv_id)

        assert deleted is True
        assert await store.get(conv_id) is None

    @pytest.mark.asyncio
    async def test_list_conversations(self, user):
        """Test listing conversations."""
        store = DjangoConversationStore(user=user)

        for i in range(3):
            conv = Conversation(id=uuid4(), title=f"Conv {i}")
            await store.save(conv)

        convs = await store.list_conversations()

        assert len(convs) == 3

    @pytest.mark.asyncio
    async def test_add_message(self, user):
        """Test adding a message to a conversation."""
        store = DjangoConversationStore(user=user)

        conv_id = uuid4()
        conv = Conversation(id=conv_id, title="Test")
        await store.save(conv)

        msg = ConversationMessage(
            id=uuid4(),
            role="user",
            content="Hello!",
        )
        await store.add_message(conv_id, msg)

        messages = await store.get_messages(conv_id)

        assert len(messages) == 1
        assert messages[0].role == "user"
        assert messages[0].content == "Hello!"


@requires_postgres
@pytest.mark.django_db(transaction=True)
class TestDjangoTaskStore:
    """Tests for DjangoTaskStore."""

    @pytest.mark.asyncio
    async def test_save_and_get(self, user):
        """Test saving and getting a task list."""
        store = DjangoTaskStore(user=user)

        list_id = uuid4()
        task_list = TaskList(
            id=list_id,
            name="Test Tasks",
            tasks=[
                Task(id=uuid4(), name="Task 1", state=TaskState.NOT_STARTED),
                Task(id=uuid4(), name="Task 2", state=TaskState.IN_PROGRESS),
            ],
        )

        await store.save(task_list)
        retrieved = await store.get(list_id)

        assert retrieved is not None
        assert retrieved.name == "Test Tasks"
        assert len(retrieved.tasks) == 2

    @pytest.mark.asyncio
    async def test_update_task(self, user):
        """Test updating a task state."""
        store = DjangoTaskStore(user=user)

        list_id = uuid4()
        task_id = uuid4()
        task_list = TaskList(
            id=list_id,
            name="Test",
            tasks=[Task(id=task_id, name="Task 1", state=TaskState.NOT_STARTED)],
        )
        await store.save(task_list)

        await store.update_task(list_id, task_id, state=TaskState.COMPLETE)

        retrieved = await store.get(list_id)
        assert retrieved.tasks[0].state == TaskState.COMPLETE


@pytest.mark.django_db
class TestPersistenceHelpers:
    """Tests for persistence helper functions."""

    def test_get_persistence_config(self, user):
        """Test getting a persistence config."""
        config = get_persistence_config(user)

        assert config.memory_store is not None
        assert config.conversation_store is not None
        assert config.task_store is not None
        assert config.preferences_store is not None

    def test_get_persistence_manager(self, user):
        """Test getting a persistence manager."""
        manager = get_persistence_manager(user)

        assert manager.memory is not None
        assert manager.conversations is not None
        assert manager.tasks is not None
        assert manager.preferences is not None

