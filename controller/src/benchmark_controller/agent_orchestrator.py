"""Agent Orchestrator adapter with a read-only preflight boundary."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .adapters import ADE_DESCRIPTORS, ComponentDescriptor
from .external import ControlledAdapter
from .ledger import Ledger

DEFAULT_AO_CLI = "/Applications/Agent Orchestrator.app/Contents/Resources/daemon/ao"
READY_STATUSES = {"contract-ready", "installed-ready"}


@dataclass(frozen=True)
class AgentOrchestratorPreflight:
    daemon: dict[str, Any]
    project: dict[str, Any]
    sessions: dict[str, Any]
    doctor: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "daemon": self.daemon,
            "project": self.project,
            "sessions": self.sessions,
            "doctor": self.doctor,
            "agent_sessions_started": False,
        }


class AgentOrchestratorNotReadyError(RuntimeError):
    """Raised before any mutating AO operation when readiness is incomplete."""


class AgentOrchestratorAdapter:
    """Wrap AO's CLI without allowing implicit session creation or fallback."""

    def __init__(
        self,
        workspace: Path,
        ledger: Ledger,
        *,
        permission_mode: str = "approve-reads",
        cli_path: str = DEFAULT_AO_CLI,
    ) -> None:
        self.descriptor: ComponentDescriptor = ADE_DESCRIPTORS["agent-orchestrator"]
        self.runtime = ControlledAdapter(workspace, ledger, permission_mode=permission_mode)  # type: ignore[arg-type]
        self.cli_path = cli_path

    def read_only_preflight(self, *, project_id: str) -> AgentOrchestratorPreflight:
        """Inspect AO health and registration; this method never spawns a session."""

        doctor = self._json_command(("doctor", "--json"), stage_id="intake")
        daemon = self._json_command(("status", "--json"), stage_id="intake")
        project = self._json_command(("project", "get", project_id, "--json"), stage_id="intake")
        sessions = self._json_command(("session", "ls", "--json"), stage_id="intake")
        return AgentOrchestratorPreflight(daemon=daemon, project=project, sessions=sessions, doctor=doctor)

    def spawn(self, *, project_id: str, name: str, issue: str, prompt: str) -> dict[str, Any]:
        self._assert_ready()
        return self._json_command(
            (
                "spawn",
                "--project",
                project_id,
                "--name",
                name,
                "--issue",
                issue,
                "--prompt",
                prompt,
                "--kind",
                "worker",
                "--mode",
                "chat",
            ),
            stage_id="intake",
            access="write",
        )

    def _assert_ready(self) -> None:
        if self.descriptor.implementation_status not in READY_STATUSES:
            raise AgentOrchestratorNotReadyError(
                f"Agent Orchestrator is {self.descriptor.implementation_status}; no session started"
            )

    def _json_command(
        self,
        args: tuple[str, ...],
        *,
        stage_id: str,
        access: str = "read",
    ) -> dict[str, Any]:
        result = self.runtime.run(
            (self.cli_path, *args),
            stage_id=stage_id,
            actor="infrastructure",
            access=access,  # type: ignore[arg-type]
            time_category="orchestration_overhead",
        )
        if result.returncode != 0:
            raise RuntimeError(f"Agent Orchestrator command failed: {args[0]}")
        try:
            parsed = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Agent Orchestrator returned non-JSON output: {args[0]}") from exc
        if not isinstance(parsed, dict):
            raise RuntimeError(f"Agent Orchestrator returned unexpected JSON: {args[0]}")
        return parsed
