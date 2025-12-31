"""
Tests for django_agent_runtime API views.
"""

import pytest
from uuid import uuid4
from unittest.mock import patch, MagicMock

from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from django_agent_runtime.models import AgentRun, AgentConversation, AgentEvent
from django_agent_runtime.models.base import RunStatus


@pytest.fixture
def api_client():
    """Create an API client."""
    return APIClient()


@pytest.fixture
def authenticated_client(api_client, user):
    """Create an authenticated API client."""
    api_client.force_authenticate(user=user)
    return api_client


@pytest.mark.django_db
class TestAgentConversationAPI:
    """Tests for AgentConversation API."""
    
    def test_list_conversations_unauthenticated(self, api_client):
        """Test that unauthenticated users cannot list conversations."""
        url = reverse("v1:agent_runtime:conversation-list")
        response = api_client.get(url)
        
        assert response.status_code == status.HTTP_401_UNAUTHORIZED
    
    def test_list_conversations(self, authenticated_client, conversation):
        """Test listing conversations."""
        url = reverse("v1:agent_runtime:conversation-list")
        response = authenticated_client.get(url)
        
        assert response.status_code == status.HTTP_200_OK
        assert len(response.data) >= 1
    
    def test_create_conversation(self, authenticated_client):
        """Test creating a conversation."""
        url = reverse("v1:agent_runtime:conversation-list")
        data = {
            "agent_key": "test-agent",
            "title": "New Conversation",
        }
        
        response = authenticated_client.post(url, data, format="json")
        
        assert response.status_code == status.HTTP_201_CREATED
        assert response.data["agent_key"] == "test-agent"
        assert response.data["title"] == "New Conversation"
    
    def test_get_conversation(self, authenticated_client, conversation):
        """Test getting a single conversation."""
        url = reverse("v1:agent_runtime:conversation-detail", args=[conversation.id])
        response = authenticated_client.get(url)
        
        assert response.status_code == status.HTTP_200_OK
        assert response.data["id"] == str(conversation.id)
    
    def test_cannot_access_other_users_conversation(self, authenticated_client, db):
        """Test that users cannot access other users' conversations."""
        from django.contrib.auth import get_user_model
        User = get_user_model()
        
        other_user = User.objects.create_user(
            email="other@example.com",
            password="testpass123",
        )
        other_conv = AgentConversation.objects.create(
            user=other_user,
            agent_key="test-agent",
        )
        
        url = reverse("v1:agent_runtime:conversation-detail", args=[other_conv.id])
        response = authenticated_client.get(url)
        
        assert response.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.django_db
class TestAgentRunAPI:
    """Tests for AgentRun API."""
    
    def test_list_runs_unauthenticated(self, api_client):
        """Test that unauthenticated users cannot list runs."""
        url = reverse("v1:agent_runtime:run-list")
        response = api_client.get(url)
        
        assert response.status_code == status.HTTP_401_UNAUTHORIZED
    
    def test_list_runs(self, authenticated_client, agent_run):
        """Test listing runs."""
        url = reverse("v1:agent_runtime:run-list")
        response = authenticated_client.get(url)
        
        assert response.status_code == status.HTTP_200_OK
    
    def test_create_run(self, authenticated_client, conversation):
        """Test creating a run."""
        url = reverse("v1:agent_runtime:run-list")
        data = {
            "agent_key": "test-agent",
            "conversation_id": str(conversation.id),
            "messages": [{"role": "user", "content": "Hello"}],
        }
        
        response = authenticated_client.post(url, data, format="json")
        
        assert response.status_code == status.HTTP_201_CREATED
        assert response.data["agent_key"] == "test-agent"
        assert response.data["status"] == "queued"
    
    def test_create_run_without_conversation(self, authenticated_client):
        """Test creating a run without a conversation."""
        url = reverse("v1:agent_runtime:run-list")
        data = {
            "agent_key": "standalone-agent",
            "messages": [{"role": "user", "content": "Hello"}],
        }
        
        response = authenticated_client.post(url, data, format="json")
        
        assert response.status_code == status.HTTP_201_CREATED
    
    def test_create_run_idempotency(self, authenticated_client, conversation):
        """Test idempotency key prevents duplicate runs."""
        url = reverse("v1:agent_runtime:run-list")
        data = {
            "agent_key": "test-agent",
            "conversation_id": str(conversation.id),
            "messages": [{"role": "user", "content": "Hello"}],
            "idempotency_key": "unique-key-123",
        }
        
        response1 = authenticated_client.post(url, data, format="json")
        response2 = authenticated_client.post(url, data, format="json")
        
        assert response1.status_code == status.HTTP_201_CREATED
        assert response2.status_code == status.HTTP_200_OK
        assert response1.data["id"] == response2.data["id"]
    
    def test_get_run_detail(self, authenticated_client, agent_run):
        """Test getting run details."""
        url = reverse("v1:agent_runtime:run-detail", args=[agent_run.id])
        response = authenticated_client.get(url)
        
        assert response.status_code == status.HTTP_200_OK
        assert response.data["id"] == str(agent_run.id)
    
    def test_cancel_run(self, authenticated_client, agent_run):
        """Test cancelling a run."""
        url = reverse("v1:agent_runtime:run-cancel", args=[agent_run.id])
        response = authenticated_client.post(url)
        
        assert response.status_code == status.HTTP_200_OK
        assert response.data["status"] == "cancellation_requested"
        
        agent_run.refresh_from_db()
        assert agent_run.cancel_requested_at is not None
    
    def test_cancel_completed_run_fails(self, authenticated_client, completed_run):
        """Test that cancelling a completed run fails."""
        url = reverse("v1:agent_runtime:run-cancel", args=[completed_run.id])
        response = authenticated_client.post(url)

        assert response.status_code == status.HTTP_400_BAD_REQUEST


@pytest.mark.django_db
class TestAnonymousSessionAPI:
    """Tests for anonymous session authentication."""

    @pytest.fixture
    def anonymous_session(self, db):
        """Create an anonymous session."""
        from accounts.models import AnonymousSession
        return AnonymousSession.objects.create()

    def test_create_conversation_with_anonymous_token(self, api_client, anonymous_session):
        """Test creating a conversation with anonymous token."""
        url = reverse("v1:agent_runtime:conversation-list")
        data = {
            "agent_key": "test-agent",
            "title": "Anonymous Conversation",
        }

        response = api_client.post(
            url,
            data,
            format="json",
            HTTP_X_ANONYMOUS_TOKEN=anonymous_session.token,
        )

        assert response.status_code == status.HTTP_201_CREATED
        assert response.data["agent_key"] == "test-agent"

        # Verify conversation is linked to anonymous session
        conv = AgentConversation.objects.get(id=response.data["id"])
        assert conv.anonymous_session == anonymous_session
        assert conv.user is None

    def test_list_conversations_with_anonymous_token(self, api_client, anonymous_session):
        """Test listing conversations with anonymous token."""
        # Create a conversation for this session
        conv = AgentConversation.objects.create(
            anonymous_session=anonymous_session,
            agent_key="test-agent",
        )

        url = reverse("v1:agent_runtime:conversation-list")
        response = api_client.get(
            url,
            HTTP_X_ANONYMOUS_TOKEN=anonymous_session.token,
        )

        assert response.status_code == status.HTTP_200_OK
        # Handle paginated response
        results = response.data.get("results", response.data)
        assert len(results) == 1
        assert results[0]["id"] == str(conv.id)

    def test_create_run_with_anonymous_token(self, api_client, anonymous_session):
        """Test creating a run with anonymous token."""
        # Create a conversation first
        conv = AgentConversation.objects.create(
            anonymous_session=anonymous_session,
            agent_key="test-agent",
        )

        url = reverse("v1:agent_runtime:run-list")
        data = {
            "agent_key": "test-agent",
            "conversation_id": str(conv.id),
            "messages": [{"role": "user", "content": "Hello"}],
        }

        response = api_client.post(
            url,
            data,
            format="json",
            HTTP_X_ANONYMOUS_TOKEN=anonymous_session.token,
        )

        assert response.status_code == status.HTTP_201_CREATED
        assert response.data["agent_key"] == "test-agent"

        # Verify metadata contains anonymous token
        run = AgentRun.objects.get(id=response.data["id"])
        assert run.metadata.get("anonymous_token") == anonymous_session.token

    def test_invalid_anonymous_token_rejected(self, api_client):
        """Test that invalid anonymous tokens are rejected."""
        url = reverse("v1:agent_runtime:conversation-list")
        response = api_client.get(
            url,
            HTTP_X_ANONYMOUS_TOKEN="invalid-token",
        )

        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_expired_anonymous_session_rejected(self, api_client, db):
        """Test that expired anonymous sessions are rejected."""
        from accounts.models import AnonymousSession
        from django.utils import timezone
        from datetime import timedelta

        expired_session = AnonymousSession.objects.create(
            expires_at=timezone.now() - timedelta(days=1)
        )

        url = reverse("v1:agent_runtime:conversation-list")
        response = api_client.get(
            url,
            HTTP_X_ANONYMOUS_TOKEN=expired_session.token,
        )

        assert response.status_code == status.HTTP_401_UNAUTHORIZED
