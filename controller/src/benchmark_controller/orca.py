"""ORCA adapter with redacted status and workspace-isolation probes."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .adapters import ADE_DESCRIPTORS, ComponentDescriptor
from .external import ControlledAdapter, LifecycleBridge
from .ledger import Ledger

DEFAULT_ORCA_CLI = "/usr/local/bin/orca"
READY_STATUSES = {"contract-ready", "installed-ready"}


@dataclass(frozen=True)
class OrcaPreflight:
    status: dict[str, Any]
    agent_context: dict[str, Any]
    worktree: dict[str, Any]
    worktree_catalog: dict[str, Any]
    accounts: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "agent_context": self.agent_context,
            "worktree": self.worktree,
            "worktree_catalog": self.worktree_catalog,
            "accounts": self.accounts,
            "agent_sessions_started": False,
        }


class OrcaNotReadyError(RuntimeError):
    """Raised before any mutating ORCA operation when readiness is incomplete."""


class OrcaAdapter:
    """Wrap ORCA's machine-readable CLI without opening graph/workflow state."""

    def __init__(
        self,
        workspace: Path,
        ledger: Ledger,
        *,
        permission_mode: str = "approve-reads",
        cli_path: str = DEFAULT_ORCA_CLI,
    ) -> None:
        self.descriptor: ComponentDescriptor = ADE_DESCRIPTORS["orca"]
        self.runtime = ControlledAdapter(workspace, ledger, permission_mode=permission_mode)  # type: ignore[arg-type]
        self.cli_path = cli_path
        self.lifecycle = LifecycleBridge(ledger, tool="orca")

    def read_only_preflight(self) -> OrcaPreflight:
        """Inspect ORCA without opening the app, graph, terminal, or session."""

        status = self._json_command(("status", "--json"), stage_id="intake")
        agent_context = self._json_command(("agent-context", "--json"), stage_id="intake")
        worktree = self._json_command(("worktree", "current", "--json"), stage_id="intake", allow_failure=True)
        worktree_catalog = self._json_command(("worktree", "list", "--limit", "50", "--json"), stage_id="intake")
        accounts = self._json_command(("account", "list", "--json"), stage_id="intake")
        return OrcaPreflight(
            status=_status_summary(status),
            agent_context=_agent_context_summary(agent_context),
            worktree=_worktree_summary(worktree),
            worktree_catalog=_worktree_catalog_summary(worktree_catalog, self.runtime.workspace),
            accounts=_account_summary(accounts),
        )

    def start_workflow(self, *, objective: str) -> dict[str, Any]:
        self._assert_ready()
        return self._json_command(
            ("orchestration", "run-create", "--objective", objective, "--json"),
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
                event_name="workflow.start",
            )
            raise OrcaNotReadyError(f"ORCA is {self.descriptor.implementation_status}; no workflow started")

    def _json_command(
        self,
        args: tuple[str, ...],
        *,
        stage_id: str,
        access: str = "read",
        allow_failure: bool = False,
    ) -> dict[str, Any]:
        result = self.runtime.run(
            (self.cli_path, *args),
            stage_id=stage_id,
            actor="infrastructure",
            access=access,  # type: ignore[arg-type]
            time_category="orchestration_overhead",
        )
        try:
            parsed = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"ORCA returned non-JSON output: {args[0]}") from exc
        if not isinstance(parsed, dict):
            raise RuntimeError(f"ORCA returned unexpected JSON: {args[0]}")
        if result.returncode != 0 and not allow_failure:
            raise RuntimeError(f"ORCA command failed: {args[0]}")
        return parsed


def _status_summary(status: dict[str, Any]) -> dict[str, Any]:
    result = status.get("result", {})
    runtime = result.get("runtime", {})
    graph = result.get("graph", {})
    app = result.get("app", {})
    return {
        "ok": status.get("ok"),
        "app_running": app.get("running"),
        "runtime_reachable": runtime.get("reachable"),
        "runtime_state": runtime.get("state"),
        "graph_state": graph.get("state"),
        "app_version": runtime.get("appVersion"),
        "capability_count": len(runtime.get("capabilities", [])) if isinstance(runtime.get("capabilities"), list) else 0,
        "runtime_id_present": bool(runtime.get("runtimeId")),
    }


def _agent_context_summary(context: dict[str, Any]) -> dict[str, Any]:
    result = context.get("result", context)
    commands = result.get("commands", []) if isinstance(result, dict) else []
    return {
        "ok": context.get("ok", True),
        "schema_version": result.get("schemaVersion") if isinstance(result, dict) else None,
        "command_count": len(commands) if isinstance(commands, list) else 0,
        "machine_readable": isinstance(commands, list),
    }


def _worktree_summary(worktree: dict[str, Any]) -> dict[str, Any]:
    error = worktree.get("error", {})
    result = worktree.get("result", {})
    return {
        "ok": worktree.get("ok"),
        "current_worktree_found": bool(result) and worktree.get("ok") is True,
        "error_code": error.get("code") if isinstance(error, dict) else None,
    }


def _worktree_catalog_summary(catalog: dict[str, Any], workspace: Path) -> dict[str, Any]:
    result = catalog.get("result", catalog)
    items = result.get("worktrees", result.get("data", [])) if isinstance(result, dict) else []
    paths = [item.get("path") for item in items if isinstance(item, dict)] if isinstance(items, list) else []
    workspace_text = str(workspace.resolve())
    return {
        "ok": catalog.get("ok", True),
        "count": len(paths),
        "benchmark_workspace_registered": workspace_text in paths,
    }


def _account_summary(accounts: dict[str, Any]) -> dict[str, Any]:
    result = accounts.get("result", accounts)
    if not isinstance(result, dict):
        return {"auth_probe": "failed", "provider_states": {}}
    rate_limits = result.get("rateLimits", {})
    states: dict[str, int] = {}
    if isinstance(rate_limits, dict):
        for value in rate_limits.values():
            if isinstance(value, dict) and isinstance(value.get("status"), str):
                state = value["status"]
                states[state] = states.get(state, 0) + 1
    return {
        "auth_probe": "passed",
        "claude_account_count": len(result.get("claude", {}).get("accounts", [])) if isinstance(result.get("claude"), dict) else 0,
        "codex_account_count": len(result.get("codex", {}).get("accounts", [])) if isinstance(result.get("codex"), dict) else 0,
        "system_default_auth": bool(result.get("codex", {}).get("systemDefault", {}).get("hasAuth")) if isinstance(result.get("codex"), dict) else False,
        "provider_states": states,
    }
