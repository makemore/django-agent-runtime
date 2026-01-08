"""
Custom permissions and authentication for agent runtime API.

Supports both authenticated users and anonymous sessions via X-Anonymous-Token header.
"""

from rest_framework import permissions
from rest_framework.authentication import BaseAuthentication

from django_agent_runtime.conf import runtime_settings


def _get_anonymous_session_model():
    """
    Get the anonymous session model if configured.

    Returns None if anonymous sessions are not configured.
    """
    settings = runtime_settings()
    model_path = settings.ANONYMOUS_SESSION_MODEL

    if not model_path:
        return None

    try:
        from django.apps import apps
        app_label, model_name = model_path.rsplit('.', 1)
        return apps.get_model(app_label, model_name)
    except Exception:
        return None


class AnonymousSessionAuthentication(BaseAuthentication):
    """
    DRF Authentication class that authenticates via X-Anonymous-Token header.

    This allows anonymous users to access the agent runtime API by providing
    a valid anonymous session token.

    To enable, set AGENT_RUNTIME["ANONYMOUS_SESSION_MODEL"] to your session model path,
    e.g., "accounts.AnonymousSession". The model must have:
    - A `token` field
    - An `is_expired` property
    """

    def authenticate(self, request):
        """
        Authenticate the request using X-Anonymous-Token header.

        Returns a tuple of (user, auth) where user is None for anonymous sessions
        and auth is the AnonymousSession object.
        """
        token = request.headers.get('X-Anonymous-Token')
        if not token:
            token = request.query_params.get('anonymous_token')

        if not token:
            return None

        AnonymousSession = _get_anonymous_session_model()
        if not AnonymousSession:
            return None

        try:
            session = AnonymousSession.objects.get(token=token)
            if hasattr(session, 'is_expired') and session.is_expired:
                return None

            # Store the session on the request for later use
            request.anonymous_session = session

            # Return (None, session) - None user means anonymous
            # The session is the "auth" object
            return (None, session)
        except Exception:
            return None

    def authenticate_header(self, request):
        """Return a string to be used as the value of the WWW-Authenticate header."""
        return 'X-Anonymous-Token'


class IsAuthenticatedOrAnonymousSession(permissions.BasePermission):
    """
    Permission class that allows access if:
    1. User is authenticated (via Token auth), OR
    2. Request has a valid X-Anonymous-Token header
    """
    
    def has_permission(self, request, view):
        # Check if user is authenticated
        if request.user and request.user.is_authenticated:
            return True
        
        # Check if we have an anonymous session (set by AnonymousSessionAuthentication)
        if hasattr(request, 'anonymous_session') and request.anonymous_session:
            return True
        
        return False


def get_anonymous_session(request):
    """
    Helper function to get the anonymous session from a request.
    
    Returns the AnonymousSession object if present, None otherwise.
    """
    return getattr(request, 'anonymous_session', None)

