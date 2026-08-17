"""Agent Orchestrator adapter with a read-only preflight boundary."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .adapters import ADE_DESCRIPTORS, ComponentDescriptor
from .external import ControlledAdapter, LifecycleBridge
from .ledger import Ledger

DEFAULT_AO_CLI = "/Applications/Agent Orchestrator.app/Contents/Resources/daemon/ao"
READY_STATUSES = {"contract-ready", "installed-ready"}


@dataclass(frozen=True)
class AgentOrchestratorPreflight:
    daemon: dict[str, Any]
    project: dict[str, Any]
    sessions: dict[str, Any]
    doctor: dict[str, Any]
    agents: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "daemon": self.daemon,
            "project": self.project,
            "sessions": self.sessions,
            "doctor": self.doctor,
            "agents": self.agents,
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
        self.lifecycle = LifecycleBridge(ledger, tool="agent-orchestrator")

    def read_only_preflight(self, *, project_id: str) -> AgentOrchestratorPreflight:
        """Inspect AO health and registration; this method never spawns a session."""

        doctor = self._json_command(("doctor", "--json"), stage_id="intake")
        daemon = self._json_command(("status", "--json"), stage_id="intake")
        project = self._json_command(("project", "get", project_id, "--json"), stage_id="intake")
        sessions = self._json_command(("session", "ls", "--json"), stage_id="intake")
        agents = self._json_command(("agent", "ls", "--json"), stage_id="intake")
        return AgentOrchestratorPreflight(
            daemon=daemon,
            project=project,
            sessions=sessions,
            doctor=doctor,
            agents=_agent_auth_summary(agents),
        )

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

    def record_lifecycle_event(
        self,
        event: dict[str, Any],
        *,
        stage_id: str,
        actor: str,
        parent_event_id: str | None = None,
    ) -> dict[str, object]:
        self._assert_ready()
        return self.lifecycle.record_external(
            event,
            stage_id=stage_id,
            actor=actor,
            parent_event_id=parent_event_id,
        )

    def _assert_ready(self) -> None:
        if self.descriptor.implementation_status not in READY_STATUSES:
            self.lifecycle.record(
                stage_id="intake",
                actor="infrastructure",
                status="blocked",
                event_name="session.spawn",
            )
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


def _agent_auth_summary(payload: dict[str, Any]) -> dict[str, Any]:
    supported = payload.get("supported", [])
    installed = payload.get("installed", [])
    authorized = payload.get("authorized", [])
    return {
        "supported_count": len(supported) if isinstance(supported, list) else 0,
        "installed_count": len(installed) if isinstance(installed, list) else 0,
        "authorized_count": len(authorized) if isinstance(authorized, list) else 0,
        "authorized_ids": sorted(
            str(agent.get("id"))
            for agent in authorized
            if isinstance(agent, dict) and agent.get("id")
        ),
        "auth_probe": "passed",
    }
