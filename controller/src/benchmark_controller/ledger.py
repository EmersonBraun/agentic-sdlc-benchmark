"""Append-only ledger writer used by every harness and ADE adapter."""

from __future__ import annotations

import hashlib
import json
import time
import fcntl
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
        self._observed_size = -1
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._sync_sequence()

    def _sync_sequence(self) -> None:
        if not self.path.exists():
            self._observed_size = 0
            return
        size = self.path.stat().st_size
        if size == self._observed_size:
            return
        maximum = self._sequence
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            event = json.loads(line)
            if event.get("run_id") != self.run_id or event.get("task_id") != self.task_id:
                raise ValueError("Existing ledger belongs to a different run or task")
            event_id = str(event.get("event_id", ""))
            if event_id.startswith("evt_") and event_id[4:].isdigit():
                maximum = max(maximum, int(event_id[4:]))
        self._sequence = maximum
        self._observed_size = size

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
        tokens: dict[str, int] | None = None,
        cost_usd: float | None = None,
        token_cost_accounting_observed: bool | None = None,
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
        if tokens is not None:
            allowed_token_fields = {"input", "output", "cached", "reasoning"}
            if set(tokens) - allowed_token_fields:
                raise ValueError("tokens contains an unknown field")
            if any(not isinstance(value, int) or value < 0 for value in tokens.values()):
                raise ValueError("token counts must be non-negative integers")
        if cost_usd is not None and cost_usd < 0:
            raise ValueError("cost_usd must be non-negative")
        if token_cost_accounting_observed is not None and not isinstance(token_cost_accounting_observed, bool):
            raise ValueError("token_cost_accounting_observed must be boolean")

        event_payload = payload or {}
        event = {
            "schema_version": "1.0",
            "event_id": "",
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
        if tokens is not None:
            event["tokens"] = dict(tokens)
        if token_cost_accounting_observed is not None:
            event["token_cost_accounting_observed"] = token_cost_accounting_observed
        if cost_usd is not None:
            event["cost_usd"] = round(cost_usd, 8)
        # Sequence allocation and append are one inter-process critical section.
        # Every benchmark writer uses this ledger implementation, so flock keeps
        # event IDs unique without introducing a mutable side database.
        with self.path.open("a+", encoding="utf-8") as stream:
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
            self._observed_size = -1
            self._sync_sequence()
            self._sequence += 1
            event["event_id"] = f"evt_{self._sequence:06d}"
            stream.write(json.dumps(event, sort_keys=True) + "\n")
            stream.flush()
            fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
        self._observed_size = self.path.stat().st_size
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
