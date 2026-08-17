"""Common controlled runtime boundary for ADE and harness adapters."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Mapping, Sequence

from .ledger import Ledger

AccessType = Literal["read", "write", "network"]
PermissionMode = Literal["deny-all", "approve-reads", "approve-all"]


@dataclass(frozen=True)
class PermissionPolicy:
    mode: PermissionMode

    def authorize(self, access: AccessType) -> None:
        allowed = {
            "deny-all": frozenset(),
            "approve-reads": frozenset({"read"}),
            "approve-all": frozenset({"read", "write", "network"}),
        }[self.mode]
        if access not in allowed:
            raise PermissionError(f"Permission mode {self.mode!r} denies {access!r} access")


@dataclass(frozen=True)
class AdapterCommandResult:
    command: tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str
    timed_out: bool = False


class ControlledAdapter:
    """Execute explicit argv commands inside a declared workspace.

    ADEs and harnesses use this same boundary. They may differ in orchestration
    above it, but not in path containment, permission accounting, timeout
    handling, or ledger redaction.
    """

    adapter_version = "external-adapter-contract-v1.0"

    def __init__(self, workspace: Path, ledger: Ledger, *, permission_mode: PermissionMode) -> None:
        self.workspace = workspace.resolve()
        self.ledger = ledger
        self.permissions = PermissionPolicy(permission_mode)

    def prepare(self) -> Path:
        self.workspace.mkdir(parents=True, exist_ok=True)
        self.ledger.record(
            stage_id="intake",
            actor="controller",
            event_type="adapter.workspace.prepared",
            time_category="harness_overhead",
            duration_ms=0,
            status="completed",
            payload={"workspace_sha256": _sha256_text(str(self.workspace))},
            tool=self.adapter_version,
        )
        return self.workspace

    def run(
        self,
        command: Sequence[str],
        *,
        stage_id: str,
        actor: str,
        access: AccessType,
        time_category: str = "orchestration_overhead",
        timeout_seconds: float = 120,
        env: Mapping[str, str] | None = None,
    ) -> AdapterCommandResult:
        normalized = _validate_command(command)
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self.prepare()
        command_metadata = {
            "executable": normalized[0],
            "argc": len(normalized),
            "argv_sha256": _sha256_text(json.dumps(normalized, separators=(",", ":"))),
            "access": access,
            "timeout_seconds": timeout_seconds,
        }
        try:
            self.permissions.authorize(access)
        except PermissionError:
            self.ledger.record(
                stage_id=stage_id,
                actor=actor,
                event_type="adapter.command.blocked",
                time_category="orchestration_overhead",
                duration_ms=0,
                status="blocked",
                payload=command_metadata,
                tool=self.adapter_version,
            )
            raise

        merged_env = os.environ.copy()
        if env:
            merged_env.update(env)
        with self.ledger.span(
            stage_id=stage_id,
            actor=actor,
            event_type="adapter.command.executed",
            time_category=time_category,
            payload=command_metadata,
            tool=self.adapter_version,
        ) as span:
            try:
                completed = subprocess.run(
                    list(normalized),
                    cwd=self.workspace,
                    env=merged_env,
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=timeout_seconds,
                )
                result = AdapterCommandResult(
                    command=normalized,
                    returncode=completed.returncode,
                    stdout=completed.stdout,
                    stderr=completed.stderr,
                )
            except subprocess.TimeoutExpired as exc:
                span.update({"status": "failed", "timed_out": True})
                result = AdapterCommandResult(
                    command=normalized,
                    returncode=124,
                    stdout=exc.stdout or "",
                    stderr=exc.stderr or "",
                    timed_out=True,
                )
            else:
                span.update(
                    {
                        "returncode": result.returncode,
                        "timed_out": False,
                        "stdout_length": len(result.stdout),
                        "stderr_length": len(result.stderr),
                    }
                )
        return result

    def hash_file(self, relative_path: str, *, stage_id: str = "documentation") -> str:
        candidate = (self.workspace / relative_path).resolve()
        try:
            candidate.relative_to(self.workspace)
        except ValueError as exc:
            raise ValueError("artifact path escapes adapter workspace") from exc
        digest = hashlib.sha256(candidate.read_bytes()).hexdigest()
        self.ledger.record(
            stage_id=stage_id,
            actor="controller",
            event_type="adapter.artifact.hashed",
            time_category="instrumentation_overhead",
            duration_ms=0,
            status="completed",
            payload={"path_sha256": _sha256_text(relative_path), "artifact_sha256": digest},
            tool=self.adapter_version,
        )
        return digest


class LifecycleBridge:
    """Record ADE lifecycle transitions through the common event contract."""

    def __init__(self, ledger: Ledger, *, tool: str) -> None:
        if not tool:
            raise ValueError("tool must be non-empty")
        self.ledger = ledger
        self.tool = tool

    def record(
        self,
        *,
        stage_id: str,
        actor: str,
        status: str,
        duration_ms: float = 0,
        event_name: str = "stage",
        parent_event_id: str | None = None,
    ) -> dict[str, object]:
        if not event_name:
            raise ValueError("event_name must be non-empty")
        if status not in {"started", "completed", "failed", "blocked", "redacted"}:
            raise ValueError(f"Unknown lifecycle status: {status!r}")
        return self.ledger.record(
            stage_id=stage_id,
            actor=actor,
            event_type=f"lifecycle.{event_name}",
            time_category="orchestration_overhead",
            duration_ms=duration_ms,
            status=status,
            payload={"stage_id": stage_id, "event_name": event_name},
            tool=self.tool,
            parent_event_id=parent_event_id,
        )


def _validate_command(command: Sequence[str]) -> tuple[str, ...]:
    if not command or any(not isinstance(part, str) or not part for part in command):
        raise ValueError("command must be a non-empty sequence of non-empty strings")
    return tuple(command)


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()
