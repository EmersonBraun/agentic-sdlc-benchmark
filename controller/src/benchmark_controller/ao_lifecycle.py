"""Normalize Agent Orchestrator session-state observations into lifecycle events."""

from __future__ import annotations

from typing import Any, Mapping

from .external import LifecycleBridge

_STATE_STATUS = {
    "queued": "started",
    "starting": "started",
    "initializing": "started",
    "running": "started",
    "working": "started",
    "active": "started",
    "waiting": "started",
    "awaiting_input": "started",
    "idle": "started",
    "completed": "completed",
    "complete": "completed",
    "terminated": "completed",
    "stopped": "completed",
    "killed": "completed",
    "failed": "failed",
    "error": "failed",
    "blocked": "blocked",
}


def normalize_session_snapshot(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    """Convert one public AO session snapshot into the common event shape."""

    session = snapshot.get("session", snapshot)
    if not isinstance(session, Mapping):
        raise ValueError("AO session snapshot must contain an object")
    session_id = session.get("id", session.get("sessionId"))
    raw_state = session.get("status", session.get("state", session.get("lifecycleStatus")))
    if not isinstance(session_id, str) or not session_id:
        raise ValueError("AO session snapshot requires an id")
    if not isinstance(raw_state, str) or not raw_state:
        raise ValueError("AO session snapshot requires a state")
    state = raw_state.strip().lower().replace("-", "_").replace(" ", "_")
    try:
        status = _STATE_STATUS[state]
    except KeyError as exc:
        raise ValueError(f"Unknown AO session state: {raw_state!r}") from exc
    return {
        "event_name": "session.state",
        "source_event_type": "ao.session.state",
        "status": status,
        "duration_ms": 0,
        "entity_id": session_id,
        "snapshot_state": state,
    }


class SessionLifecycleObserver:
    """Record only state transitions observed through AO's public read surface."""

    def __init__(self, bridge: LifecycleBridge) -> None:
        self.bridge = bridge
        self._last_state: dict[str, str] = {}

    def observe(
        self,
        snapshot: Mapping[str, Any],
        *,
        stage_id: str = "intake",
        actor: str = "infrastructure",
        parent_event_id: str | None = None,
    ) -> dict[str, object] | None:
        event = normalize_session_snapshot(snapshot)
        state = str(event["snapshot_state"])
        session_id = str(event["entity_id"])
        if self._last_state.get(session_id) == state:
            return None
        recorded = self.bridge.record_external(
            event,
            stage_id=stage_id,
            actor=actor,
            parent_event_id=parent_event_id,
        )
        self._last_state[session_id] = state
        return recorded
