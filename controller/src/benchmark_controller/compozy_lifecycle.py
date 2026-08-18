"""Normalize Compozy session events into the shared lifecycle contract."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any


_LIFECYCLE_EVENTS: dict[str, tuple[str, str]] = {
    "hook.dispatch.start": ("session.hook", "started"),
    "hook.dispatch.complete": ("session.hook", "completed"),
    "done": ("session.execution", "completed"),
    "error": ("session.execution", "failed"),
    "session_stopped": ("session.stop", "completed"),
    "session_cancelled": ("session.stop", "failed"),
}

_NON_LIFECYCLE_EVENTS = frozenset(
    {
        "agent_message",
        "available_commands_update",
        "system",
        "thought",
        "tool_call",
        "tool_result",
        "usage",
        "user_message",
    }
)


def normalize_compozy_event(event: Mapping[str, Any]) -> dict[str, Any] | None:
    """Return only safe lifecycle metadata; never return prompt or content fields."""

    event_type = event.get("type")
    if not isinstance(event_type, str) or not event_type:
        raise ValueError("Compozy event requires a non-empty type")
    if event_type in _NON_LIFECYCLE_EVENTS:
        return None
    try:
        event_name, status = _LIFECYCLE_EVENTS[event_type]
    except KeyError as exc:
        raise ValueError(f"Unknown Compozy event type: {event_type!r}") from exc

    entity_id = event.get("session_id") or event.get("sessionId")
    normalized: dict[str, Any] = {
        "event_name": event_name,
        "source_event_type": event_type,
        "status": status,
        "duration_ms": 0,
    }
    if entity_id is not None:
        normalized["entity_id"] = str(entity_id)
    return normalized


def normalize_compozy_events(events: Iterable[Mapping[str, Any]]) -> tuple[dict[str, Any], ...]:
    """Normalize an event stream while failing closed on an unknown event type."""

    normalized: list[dict[str, Any]] = []
    for event in events:
        candidate = normalize_compozy_event(event)
        if candidate is not None:
            normalized.append(candidate)
    return tuple(normalized)
