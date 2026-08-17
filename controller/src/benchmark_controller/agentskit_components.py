"""Benchmark-side mapping for public AgentsKit component actions."""

from __future__ import annotations

from numbers import Real
from typing import Any, Mapping

from .agentskit import AgentsKitLedgerBridge

PUBLIC_COMPONENTS = frozenset({"doc-bridge", "playbook", "specialized-agents", "code-review"})
PHASES = frozenset({"start", "complete", "error"})


class AgentsKitComponentActionBridge:
    """Convert bounded component action metadata into AgentsKit ledger events.

    The bridge accepts metadata only. Content, arguments, results, prompts, and
    findings are represented by lengths or fixed redaction markers and are
    never passed through as payload text.
    """

    def __init__(self, event_bridge: AgentsKitLedgerBridge) -> None:
        self.event_bridge = event_bridge

    def record(self, action: Mapping[str, Any]) -> dict[str, Any]:
        component = action.get("component")
        operation = action.get("operation")
        phase = action.get("phase")
        if component not in PUBLIC_COMPONENTS:
            raise ValueError(f"Unknown public AgentsKit component: {component!r}")
        if not isinstance(operation, str) or not operation:
            raise ValueError("component action requires a non-empty operation")
        if phase not in PHASES:
            raise ValueError(f"component action phase is invalid: {phase!r}")

        if component == "doc-bridge":
            if operation != "lookup":
                raise ValueError("doc-bridge supports only lookup actions")
            event = self._doc_bridge_event(action)
        elif component == "playbook":
            if operation != "step":
                raise ValueError("playbook supports only step actions")
            event = self._playbook_event(action)
        elif component == "specialized-agents":
            if operation != "delegate":
                raise ValueError("specialized-agents supports only delegate actions")
            event = self._specialized_agent_event(action)
        else:
            if operation != "review":
                raise ValueError("code-review supports only review actions")
            event = self._code_review_event(action)
        return self.event_bridge.on_event(event, stage_id=action.get("stage_id", "implementation"))

    @staticmethod
    def _duration(action: Mapping[str, Any]) -> float:
        duration = action.get("durationMs", 0)
        if not isinstance(duration, Real) or isinstance(duration, bool) or duration < 0:
            raise ValueError("durationMs must be a non-negative number")
        return float(duration)

    def _doc_bridge_event(self, action: Mapping[str, Any]) -> dict[str, Any]:
        phase = action["phase"]
        if phase == "start":
            return {"type": "tool:start", "name": "agentskit.doc-bridge.lookup", "args": {}}
        if phase == "complete":
            return {
                "type": "tool:end",
                "name": "agentskit.doc-bridge.lookup",
                "result": "[redacted]",
                "durationMs": self._duration(action),
            }
        return {"type": "error", "error": RuntimeError("doc-bridge action failed")}

    def _playbook_event(self, action: Mapping[str, Any]) -> dict[str, Any]:
        step = action.get("step")
        if not isinstance(step, int) or isinstance(step, bool) or step < 1:
            raise ValueError("playbook step must be a positive integer")
        status = {"start": "start", "complete": "ok", "error": "error"}[action["phase"]]
        return {
            "type": "progress",
            "label": "agentskit.playbook.step",
            "status": status,
            "durationMs": self._duration(action),
        }

    def _specialized_agent_event(self, action: Mapping[str, Any]) -> dict[str, Any]:
        name = action.get("name")
        depth = action.get("depth", 0)
        if not isinstance(name, str) or not name:
            raise ValueError("specialized-agent delegate requires a name")
        if not isinstance(depth, int) or isinstance(depth, bool) or depth < 0:
            raise ValueError("specialized-agent delegate depth must be a non-negative integer")
        if action["phase"] == "start":
            return {"type": "agent:delegate:start", "name": name, "task": "[redacted]", "depth": depth}
        if action["phase"] == "complete":
            return {
                "type": "agent:delegate:end",
                "name": name,
                "result": "[redacted]",
                "durationMs": self._duration(action),
                "depth": depth,
            }
        return {"type": "error", "error": RuntimeError("specialized-agent action failed")}

    def _code_review_event(self, action: Mapping[str, Any]) -> dict[str, Any]:
        status = {"start": "start", "complete": "ok", "error": "error"}[action["phase"]]
        return {
            "type": "progress",
            "label": "agentskit.code-review",
            "status": status,
            "durationMs": self._duration(action),
        }
