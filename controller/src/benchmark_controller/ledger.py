"""Append-only ledger writer used by every harness and ADE adapter."""

from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator
from contextlib import contextmanager

from .ids import validate_id

STAGES = {
    "intake",
    "requirements",
    "planning",
    "decomposition",
    "implementation",
    "local-testing",
    "pull-request",
    "ci-qa",
    "review",
    "merge",
    "documentation",
}
ACTORS = {
    "controller",
    "planner",
    "executor",
    "fixer",
    "reviewer-functional",
    "reviewer-security",
    "reviewer-qa",
    "oracle",
    "evaluator",
    "human-operator",
    "infrastructure",
}
TIME_CATEGORIES = {
    "effective_work",
    "human_touch",
    "orchestration_overhead",
    "harness_overhead",
    "instrumentation_overhead",
    "external_wait",
}


def _sha256_payload(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class Ledger:
    """Write one JSON object per line while preserving event order."""

    def __init__(self, path: Path, *, run_id: str, task_id: str) -> None:
        self.path = path
        self.run_id = validate_id(run_id, "run")
        self.task_id = validate_id(task_id, "task")
        self._sequence = 0
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def record(
        self,
        *,
        stage_id: str,
        actor: str,
        event_type: str,
        time_category: str,
        duration_ms: float,
        status: str,
        payload: dict[str, Any] | None = None,
        tool: str | None = None,
        parent_event_id: str | None = None,
        artifact_refs: list[str] | None = None,
    ) -> dict[str, Any]:
        if stage_id not in STAGES:
            raise ValueError(f"Unknown stage: {stage_id!r}")
        if actor not in ACTORS:
            raise ValueError(f"Unknown actor: {actor!r}")
        if time_category not in TIME_CATEGORIES:
            raise ValueError(f"Unknown time category: {time_category!r}")
        if status not in {"started", "completed", "failed", "blocked", "redacted"}:
            raise ValueError(f"Unknown event status: {status!r}")
        if duration_ms < 0:
            raise ValueError("duration_ms must be non-negative")

        self._sequence += 1
        event_id = f"evt_{self._sequence:06d}"
        event_payload = payload or {}
        event = {
            "schema_version": "1.0",
            "event_id": event_id,
            "run_id": self.run_id,
            "task_id": self.task_id,
            "stage_id": stage_id,
            "actor": actor,
            "event_type": event_type,
            "time_category": time_category,
            "occurred_at": datetime.now(timezone.utc).isoformat(),
            "monotonic_start_ns": time.monotonic_ns(),
            "monotonic_end_ns": time.monotonic_ns(),
            "duration_ms": round(duration_ms, 3),
            "parent_event_id": parent_event_id,
            "tool": tool,
            "status": status,
            "artifact_refs": artifact_refs or [],
            "payload_sha256": _sha256_payload(event_payload),
        }
        with self.path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(event, sort_keys=True) + "\n")
        return event

    @contextmanager
    def span(
        self,
        *,
        stage_id: str,
        actor: str,
        event_type: str,
        time_category: str,
        payload: dict[str, Any] | None = None,
        tool: str | None = None,
    ) -> Iterator[dict[str, Any]]:
        start = time.monotonic_ns()
        try:
            result: dict[str, Any] = {"status": "completed"}
            yield result
        except Exception as exc:
            duration_ms = (time.monotonic_ns() - start) / 1_000_000
            self.record(
                stage_id=stage_id,
                actor=actor,
                event_type=event_type,
                time_category=time_category,
                duration_ms=duration_ms,
                status="failed",
                payload={**(payload or {}), "error_type": type(exc).__name__},
                tool=tool,
            )
            raise
        else:
            duration_ms = (time.monotonic_ns() - start) / 1_000_000
            self.record(
                stage_id=stage_id,
                actor=actor,
                event_type=event_type,
                time_category=time_category,
                duration_ms=duration_ms,
                status=result.get("status", "completed"),
                payload={**(payload or {}), **{key: value for key, value in result.items() if key != "status"}},
                tool=tool,
            )

