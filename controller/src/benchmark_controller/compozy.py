"""Compozy adapter with read-only runtime, workspace, and permission probes."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .adapters import ADE_DESCRIPTORS, ComponentDescriptor
from .external import ControlledAdapter, LifecycleBridge
from .ledger import Ledger

DEFAULT_COMPOZY_CLI = "compozy"
READY_STATUSES = {"contract-ready", "installed-ready"}


@dataclass(frozen=True)
class CompozyPreflight:
    status: dict[str, Any]
    workspace: dict[str, Any]
    config: dict[str, Any]
    sessions: dict[str, Any]
    providers: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "workspace": self.workspace,
            "config": self.config,
            "sessions": self.sessions,
            "providers": self.providers,
            "agent_sessions_started": False,
        }


class CompozyNotReadyError(RuntimeError):
    """Raised before any mutating Compozy operation when readiness is incomplete."""


class CompozyAdapter:
    """Wrap Compozy's JSON CLI without creating workflows or sessions."""

    def __init__(
        self,
        workspace: Path,
        ledger: Ledger,
        *,
        permission_mode: str = "approve-reads",
        cli_path: str = DEFAULT_COMPOZY_CLI,
    ) -> None:
        self.descriptor: ComponentDescriptor = ADE_DESCRIPTORS["compozy"]
        self.runtime = ControlledAdapter(workspace, ledger, permission_mode=permission_mode)  # type: ignore[arg-type]
        self.cli_path = cli_path
        self.lifecycle = LifecycleBridge(ledger, tool="compozy")

    def read_only_preflight(self, *, workspace_name: str) -> CompozyPreflight:
        """Inspect Compozy without starting a daemon, workflow, or agent session."""

        status = self._json_command(("status", "-o", "json"), stage_id="intake")
        workspace = self._json_command(
            ("workspace", "info", workspace_name, "-o", "json"), stage_id="intake"
        )
        config = self._json_command(("config", "show", "-o", "json"), stage_id="intake")
        sessions = self._json_command(("session", "list", "-o", "json"), stage_id="intake")
        providers = self._json_command(("provider", "list", "-o", "json"), stage_id="intake")
        return CompozyPreflight(
            status=_status_summary(status),
            workspace=_workspace_summary(workspace),
            config=_config_summary(config),
            sessions=_session_summary(sessions),
            providers=_provider_summary(providers),
        )

    def spawn(self, *, agent: str = "general") -> dict[str, Any]:
        self._assert_ready()
        return self._json_command(("session", "new", "--agent", agent, "-o", "json"), stage_id="intake", access="write")

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
            raise CompozyNotReadyError(
                f"Compozy is {self.descriptor.implementation_status}; no session started"
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
            raise RuntimeError(f"Compozy command failed: {args[0]}")
        try:
            parsed = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Compozy returned non-JSON output: {args[0]}") from exc
        if not isinstance(parsed, dict):
            raise RuntimeError(f"Compozy returned unexpected JSON: {args[0]}")
        return parsed


def _status_summary(status: dict[str, Any]) -> dict[str, Any]:
    daemon = status.get("daemon", {})
    health = status.get("health", {})
    sessions = status.get("sessions", {})
    return {
        "daemon_status": daemon.get("status"),
        "daemon_version": daemon.get("version"),
        "health_status": health.get("status"),
        "active_sessions": sessions.get("active"),
        "total_sessions": sessions.get("total"),
        "network_status": daemon.get("network", {}).get("status"),
    }


def _workspace_summary(workspace: dict[str, Any]) -> dict[str, Any]:
    registration = workspace.get("workspace", workspace)
    return {
        "status": workspace.get("status"),
        "workspace_id_present": bool(registration.get("id") or registration.get("workspace_id")),
        "workspace_name": registration.get("name"),
        "root_resolved": bool(
            registration.get("root")
            or registration.get("root_dir")
            or registration.get("path")
            or registration.get("realpath")
        ),
    }


def _config_summary(config: dict[str, Any]) -> dict[str, Any]:
    effective = config.get("config", {})
    return {
        "redacted": config.get("redacted"),
        "resolution_source": config.get("resolution_source"),
        "scope": config.get("scope"),
        "permission_mode": effective.get("permissions", {}).get("mode"),
        "workspace_auto_create": effective.get("memory", {}).get("enabled") is not None,
    }


def _session_summary(sessions: dict[str, Any]) -> dict[str, Any]:
    data = sessions.get("data", [])
    return {"count": len(data) if isinstance(data, list) else 0, "page_has_more": sessions.get("page", {}).get("has_more", False)}


def _provider_summary(providers: dict[str, Any]) -> dict[str, Any]:
    data = providers.get("providers", providers.get("data", []))
    if not isinstance(data, list):
        data = []
    states: dict[str, int] = {}
    for provider in data:
        if isinstance(provider, dict):
            auth_status = provider.get("auth_status", {})
            state = str(auth_status.get("state", "unknown")) if isinstance(auth_status, dict) else "unknown"
            states[state] = states.get(state, 0) + 1
    return {
        "count": len(data),
        "states": states,
        "auth_probe": "passed",
        "ready_count": states.get("ready", 0),
        "credential_missing_count": states.get("missing_credential", 0),
    }
