"""
Langfuse trace sink implementation.

Langfuse is an open-source LLM observability platform.
This is an OPTIONAL integration - the core runtime doesn't depend on it.

See: https://langfuse.com/
"""

import logging
from typing import Optional
from uuid import UUID

from django_agent_runtime.runtime.interfaces import TraceSink

try:
    from langfuse import Langfuse
except ImportError:
    Langfuse = None

logger = logging.getLogger(__name__)


class LangfuseTraceSink(TraceSink):
    """
    Langfuse trace sink for LLM observability.

    Sends traces to Langfuse for monitoring, debugging, and analytics.
    """

    def __init__(
        self,
        public_key: Optional[str] = None,
        secret_key: Optional[str] = None,
        host: Optional[str] = None,
    ):
        if Langfuse is None:
            raise ImportError("langfuse package is required for LangfuseTraceSink")

        self._client = Langfuse(
            public_key=public_key,
            secret_key=secret_key,
            host=host,
        )
        self._traces: dict[UUID, any] = {}

    def start_run(self, run_id: UUID, metadata: dict) -> None:
        """Start a new trace in Langfuse."""
        try:
            trace = self._client.trace(
                id=str(run_id),
                name=metadata.get("agent_key", "agent_run"),
                metadata=metadata,
            )
            self._traces[run_id] = trace
        except Exception as e:
            logger.warning(f"Failed to start Langfuse trace: {e}")

    def log_event(self, run_id: UUID, event_type: str, payload: dict) -> None:
        """Log an event to the trace."""
        trace = self._traces.get(run_id)
        if not trace:
            return

        try:
            # Map event types to Langfuse concepts
            if event_type == "assistant.message":
                trace.generation(
                    name="assistant_message",
                    output=payload.get("content", ""),
                    metadata=payload,
                )
            elif event_type == "tool.call":
                trace.span(
                    name=f"tool:{payload.get('name', 'unknown')}",
                    input=payload.get("arguments", {}),
                )
            elif event_type == "tool.result":
                # Tool results are logged as part of the span
                pass
            else:
                # Generic event
                trace.event(
                    name=event_type,
                    metadata=payload,
                )
        except Exception as e:
            logger.warning(f"Failed to log Langfuse event: {e}")

    def end_run(self, run_id: UUID, outcome: str, metadata: Optional[dict] = None) -> None:
        """End the trace."""
        trace = self._traces.pop(run_id, None)
        if not trace:
            return

        try:
            # Update trace with final status
            status_map = {
                "succeeded": "SUCCESS",
                "failed": "ERROR",
                "cancelled": "CANCELLED",
                "timed_out": "ERROR",
            }
            trace.update(
                status=status_map.get(outcome, "UNKNOWN"),
                metadata=metadata or {},
            )
        except Exception as e:
            logger.warning(f"Failed to end Langfuse trace: {e}")

    def flush(self) -> None:
        """Flush any buffered traces to Langfuse."""
        try:
            self._client.flush()
        except Exception as e:
            logger.warning(f"Failed to flush Langfuse traces: {e}")

