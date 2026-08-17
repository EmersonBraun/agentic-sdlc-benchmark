"""Semantic bridge from public AgentsKit AgentEvents to the benchmark ledger."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from numbers import Real
from typing import Any, Mapping

from .ledger import Ledger

AGENTSKIT_COMPONENTS = frozenset(
    {
        "doc-bridge",
        "playbook",
        "specialized-agents",
        "code-review",
        "versioned-memory",
        "telemetry",
    }
)


@dataclass(frozen=True)
class AgentsKitSelection:
    enabled: bool
    components: frozenset[str]

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["components"] = sorted(self.components)
        return result


def resolve_selection(*, enabled: bool, disabled_components: tuple[str, ...] = ()) -> AgentsKitSelection:
    """Resolve the ON/ablation selection without silently enabling components."""

    unknown = set(disabled_components) - AGENTSKIT_COMPONENTS
    if unknown:
        raise ValueError(f"Unknown AgentsKit component: {sorted(unknown)!r}")
    if not enabled and disabled_components:
        raise ValueError("disabled_components only applies to AgentsKit ON")
    components = AGENTSKIT_COMPONENTS - set(disabled_components) if enabled else frozenset()
    return AgentsKitSelection(enabled=enabled, components=frozenset(components))


class AgentsKitLedgerBridge:
    """Translate canonical AgentsKit events into append-only benchmark events.

    The bridge accepts the public AgentsKit Observer event shape. It stores only
    bounded metadata and hashes the rest through ``Ledger``; prompts, model
    content, tool arguments, and tool results never enter the ledger payload.
    """

    adapter_version = "agentskit-0.3.0-source"
    tool_name = "agentskit"

    def __init__(
        self,
        ledger: Ledger,
        *,
        enabled: bool,
        disabled_components: tuple[str, ...] = (),
    ) -> None:
        self.ledger = ledger
        self.selection = resolve_selection(enabled=enabled, disabled_components=disabled_components)

    def on_event(
        self,
        event: Mapping[str, Any],
        *,
        stage_id: str = "implementation",
        actor: str = "executor",
        parent_event_id: str | None = None,
    ) -> dict[str, Any]:
        if not self.selection.enabled:
            raise RuntimeError("AgentsKit event received while the factor is OFF")
        event_type = event.get("type")
        if not isinstance(event_type, str) or not event_type:
            raise ValueError("AgentsKit event requires a non-empty type")
        if event_type not in _EVENT_SPECS:
            raise ValueError(f"Unsupported AgentsKit event type: {event_type!r}")

        _validate_event(event_type, event)
        time_category, status, duration_ms = _event_timing(event_type, event)
        tokens = _tokens_from_event(event)
        return self.ledger.record(
            stage_id=stage_id,
            actor=actor,
            event_type=f"agentskit.{event_type.replace(':', '.')}",
            time_category=time_category,
            duration_ms=duration_ms,
            status=status,
            payload=_redacted_metadata(event_type, event),
            tool=self.tool_name,
            parent_event_id=parent_event_id,
            tokens=tokens,
        )


# category, default status, duration field
_EVENT_SPECS: dict[str, tuple[str, str, str | None]] = {
    "llm:start": ("external_wait", "started", None),
    "llm:first-token": ("external_wait", "completed", "latencyMs"),
    "llm:end": ("external_wait", "completed", "durationMs"),
    "tool:start": ("effective_work", "started", None),
    "tool:end": ("effective_work", "completed", "durationMs"),
    "memory:load": ("instrumentation_overhead", "completed", None),
    "memory:save": ("instrumentation_overhead", "completed", None),
    "agent:step": ("orchestration_overhead", "completed", None),
    "agent:delegate:start": ("orchestration_overhead", "started", None),
    "agent:delegate:end": ("effective_work", "completed", "durationMs"),
    "progress": ("effective_work", "completed", "durationMs"),
    "error": ("orchestration_overhead", "failed", None),
    "run-aborted": ("orchestration_overhead", "blocked", None),
}


def _event_timing(event_type: str, event: Mapping[str, Any]) -> tuple[str, str, float]:
    category, default_status, duration_field = _EVENT_SPECS[event_type]
    status = default_status
    if event_type == "progress":
        status = {"start": "started", "ok": "completed", "skip": "completed", "error": "failed"}[event["status"]]
    duration = event.get(duration_field, 0) if duration_field else 0
    if not isinstance(duration, Real) or isinstance(duration, bool) or duration < 0:
        raise ValueError(f"{event_type} duration must be a non-negative number")
    return category, status, float(duration)


def _tokens_from_event(event: Mapping[str, Any]) -> dict[str, int] | None:
    usage = event.get("usage")
    if usage is None:
        return None
    if not isinstance(usage, Mapping):
        raise ValueError("llm usage must be an object")
    prompt = usage.get("promptTokens")
    completion = usage.get("completionTokens")
    if not all(isinstance(value, int) and not isinstance(value, bool) and value >= 0 for value in (prompt, completion)):
        raise ValueError("llm usage token counts must be non-negative integers")
    return {"input": prompt, "output": completion}


def _validate_event(event_type: str, event: Mapping[str, Any]) -> None:
    required_strings = {
        "tool:start": ("name",),
        "tool:end": ("name", "result"),
        "agent:delegate:start": ("name", "task"),
        "agent:delegate:end": ("name", "result"),
        "progress": ("label", "status"),
    }.get(event_type, ())
    for field in required_strings:
        if not isinstance(event.get(field), str) or not event[field]:
            raise ValueError(f"{event_type} requires non-empty string field {field!r}")
    if event_type == "llm:start":
        if not isinstance(event.get("messageCount"), int) or event["messageCount"] < 0:
            raise ValueError("llm:start requires a non-negative messageCount")
    if event_type == "llm:end" and not isinstance(event.get("content"), str):
        raise ValueError("llm:end requires string content")
    if event_type == "agent:step":
        if not isinstance(event.get("step"), int) or event["step"] < 1:
            raise ValueError("agent:step requires a positive step")
        if not isinstance(event.get("action"), str) or not event["action"]:
            raise ValueError("agent:step requires a non-empty action")
    if event_type in {"agent:delegate:start", "agent:delegate:end"}:
        if not isinstance(event.get("depth"), int) or event["depth"] < 0:
            raise ValueError(f"{event_type} requires a non-negative depth")
    if event_type in {"memory:load", "memory:save"}:
        if not isinstance(event.get("messageCount"), int) or event["messageCount"] < 0:
            raise ValueError(f"{event_type} requires a non-negative messageCount")
    if event_type == "progress" and event["status"] not in {"start", "ok", "skip", "error"}:
        raise ValueError("progress status is invalid")


def _redacted_metadata(event_type: str, event: Mapping[str, Any]) -> dict[str, Any]:
    """Keep only non-content metadata; Ledger stores a hash of this object."""

    metadata: dict[str, Any] = {"source_event_type": event_type}
    for field in ("model", "name", "step", "action", "depth", "messageCount", "latencyMs", "durationMs", "status"):
        value = event.get(field)
        if isinstance(value, (str, int, float)) and not isinstance(value, bool):
            metadata[field] = value
    for field in ("args", "result", "content", "task", "detail"):
        if field in event:
            value = event[field]
            metadata[f"{field}_length"] = len(value) if isinstance(value, (str, bytes, Mapping, list, tuple)) else 0
    if event_type == "error":
        metadata["error_type"] = type(event.get("error")).__name__
    return metadata
