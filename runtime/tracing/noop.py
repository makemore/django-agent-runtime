"""
No-op trace sink implementation.

Default implementation that does nothing.
Used when tracing is disabled or no trace sink is configured.
"""

from typing import Optional
from uuid import UUID

from django_agent_runtime.runtime.interfaces import TraceSink


class NoopTraceSink(TraceSink):
    """
    No-op trace sink that discards all traces.

    This is the default when tracing is not configured.
    """

    def start_run(self, run_id: UUID, metadata: dict) -> None:
        """No-op: discard trace start."""
        pass

    def log_event(self, run_id: UUID, event_type: str, payload: dict) -> None:
        """No-op: discard event."""
        pass

    def end_run(self, run_id: UUID, outcome: str, metadata: Optional[dict] = None) -> None:
        """No-op: discard trace end."""
        pass

    def flush(self) -> None:
        """No-op: nothing to flush."""
        pass

