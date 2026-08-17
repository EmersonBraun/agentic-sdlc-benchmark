"""Reference Harness: the neutral, local execution contract."""

from __future__ import annotations

import hashlib
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

from .ledger import Ledger


@dataclass(frozen=True)
class CommandResult:
    command: tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str
    timed_out: bool = False


class ReferenceHarness:
    """Execute only explicit argv commands inside a declared workspace.

    Network, GitHub, browser, and oracle integrations are represented by the
    same contract but are intentionally not implicit side effects of this
    reference implementation.
    """

    adapter_version = "reference-harness-v1.0"
    capabilities = frozenset(
        {
            "workspace",
            "shell",
            "git",
            "github",
            "browser",
            "oracle",
            "permissions",
            "context",
            "ledger",
        }
    )

    def __init__(self, workspace: Path, ledger: Ledger) -> None:
        self.workspace = workspace.resolve()
        self.ledger = ledger

    def prepare(self) -> Path:
        self.workspace.mkdir(parents=True, exist_ok=True)
        self.ledger.record(
            stage_id="intake",
            actor="controller",
            event_type="workspace.prepared",
            time_category="harness_overhead",
            duration_ms=0,
            status="completed",
            payload={"workspace": str(self.workspace)},
            tool="reference-harness",
        )
        return self.workspace

    def run(
        self,
        command: Sequence[str],
        *,
        stage_id: str,
        actor: str,
        time_category: str = "effective_work",
        timeout_seconds: float = 120,
        env: Mapping[str, str] | None = None,
    ) -> CommandResult:
        if not command or any(not isinstance(part, str) or not part for part in command):
            raise ValueError("command must be a non-empty sequence of non-empty strings")
        self.prepare()
        merged_env = os.environ.copy()
        if env:
            merged_env.update(env)
        with self.ledger.span(
            stage_id=stage_id,
            actor=actor,
            event_type="command.executed",
            time_category=time_category,
            payload={"command": list(command), "timeout_seconds": timeout_seconds},
            tool="reference-harness",
        ) as span:
            try:
                completed = subprocess.run(
                    list(command),
                    cwd=self.workspace,
                    env=merged_env,
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=timeout_seconds,
                )
                result = CommandResult(
                    command=tuple(command),
                    returncode=completed.returncode,
                    stdout=completed.stdout,
                    stderr=completed.stderr,
                )
            except subprocess.TimeoutExpired as exc:
                span.update({"status": "failed", "timed_out": True})
                result = CommandResult(
                    command=tuple(command),
                    returncode=124,
                    stdout=exc.stdout or "",
                    stderr=exc.stderr or "",
                    timed_out=True,
                )
            else:
                span.update({"returncode": result.returncode, "timed_out": False})
        return result

    def hash_file(self, relative_path: str) -> str:
        candidate = (self.workspace / relative_path).resolve()
        candidate.relative_to(self.workspace)
        digest = hashlib.sha256(candidate.read_bytes()).hexdigest()
        self.ledger.record(
            stage_id="documentation",
            actor="controller",
            event_type="artifact.hashed",
            time_category="instrumentation_overhead",
            duration_ms=0,
            status="completed",
            payload={"path": relative_path, "sha256": digest},
            tool="reference-harness",
        )
        return digest

