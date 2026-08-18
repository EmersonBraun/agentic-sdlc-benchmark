"""ORCA adapter with redacted status and workspace-isolation probes."""

from __future__ import annotations

import json
import time
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
        self.coordinator_handle: str | None = None
        self.run_id: str | None = None
        self.task_ids: set[str] = set()
        self.dispatch_bindings: dict[str, tuple[str, str]] = {}

    def read_only_preflight(self) -> OrcaPreflight:
        """Inspect ORCA without opening the app, graph, terminal, or session."""

        status = self._json_command(("status", "--json"), stage_id="intake")
        agent_context = self._json_command(("agent-context", "--json"), stage_id="intake")
        worktree = self._json_command(
            ("worktree", "current", "--json"), stage_id="intake",
            allowed_error_codes=("selector_not_found",),
        )
        worktree_catalog = self._json_command(("worktree", "list", "--limit", "50", "--json"), stage_id="intake")
        accounts = self._json_command(("account", "list", "--json"), stage_id="intake")
        return OrcaPreflight(
            status=_status_summary(status),
            agent_context=_agent_context_summary(agent_context),
            worktree=_worktree_summary(worktree),
            worktree_catalog=_worktree_catalog_summary(worktree_catalog, self.runtime.workspace),
            accounts=_account_summary(accounts),
        )

    def start_workflow(self, *, objective: str, coordinator_handle: str) -> dict[str, Any]:
        self._assert_ready()
        if self.run_id is not None or self.coordinator_handle is not None:
            raise RuntimeError("an ORCA adapter instance cannot replace its bound Run")
        result = self._json_command(
            ("orchestration", "run-create", "--objective", objective, "--from", coordinator_handle, "--json"),
            stage_id="intake",
            access="write",
        )
        run_id = result.get("result", {}).get("run", {}).get("id")
        if not isinstance(run_id, str) or not run_id:
            raise RuntimeError("ORCA run creation returned no run id")
        self.task_ids.clear()
        self.coordinator_handle = coordinator_handle
        self.run_id = run_id
        return result

    def create_task(self, *, run_id: str, coordinator_handle: str, spec: str, title: str) -> dict[str, Any]:
        self._assert_ready()
        if not all((run_id, coordinator_handle, spec, title)):
            raise ValueError("run_id, coordinator_handle, spec, and title must be non-empty")
        self._assert_bound(run_id=run_id, coordinator_handle=coordinator_handle)
        result = self._json_command(
            ("orchestration", "task-create", "--run", run_id, "--from", coordinator_handle,
             "--task-title", title, "--spec", spec, "--json"),
            stage_id="planning", access="write",
        )
        task_id = result.get("result", {}).get("task", {}).get("id")
        if not isinstance(task_id, str) or not task_id:
            raise RuntimeError("ORCA task creation returned no task id")
        self.task_ids.add(task_id)
        return result

    def _dispatch_to_ready_terminal(
        self, *, task_id: str, terminal_handle: str, coordinator_handle: str
    ) -> dict[str, Any]:
        """Private primitive used only after adapter-verified TUI readiness."""
        self._assert_ready()
        if not all((task_id, terminal_handle, coordinator_handle)):
            raise ValueError("task_id, terminal_handle, and coordinator_handle must be non-empty")
        self._assert_bound(coordinator_handle=coordinator_handle)
        return self._json_command(
            ("orchestration", "dispatch", "--task", task_id, "--to", terminal_handle,
             "--from", coordinator_handle, "--inject", "--json"),
            stage_id="implementation", access="write",
        )

    def start_ready_dispatch(
        self,
        *,
        task_id: str,
        coordinator_handle: str,
        agent_command: str,
        title: str = "benchmark-orca-worker",
        timeout_ms: int = 120000,
    ) -> dict[str, Any]:
        """Create an agent terminal, prove TUI readiness, then inject the Dispatch."""
        self._assert_ready()
        if not all((task_id, coordinator_handle, agent_command, title)) or timeout_ms <= 0:
            raise ValueError("ready dispatch requires non-empty identities/command and positive timeout")
        if task_id not in self.task_ids:
            raise PermissionError("task id is not bound to this ORCA adapter")
        if task_id in self.dispatch_bindings:
            raise RuntimeError("task already has a bound ORCA Dispatch")
        selector = self._workspace_selector()
        created = self._json_command(
            ("terminal", "create", "--worktree", selector, "--title", title,
             "--command", agent_command, "--json"),
            stage_id="implementation", access="write",
        )
        terminal = created.get("result", {}).get("terminal", {})
        handle = terminal.get("handle") if isinstance(terminal, dict) else None
        if not isinstance(handle, str) or not handle:
            raise RuntimeError("ORCA terminal creation returned no handle")
        try:
            waited = self._json_command(
                ("terminal", "wait", "--terminal", handle, "--for", "tui-idle",
                 "--timeout-ms", str(timeout_ms), "--json"),
                stage_id="implementation", access="write",
            )
            wait = waited.get("result", {}).get("wait", {})
            if not isinstance(wait, dict) or wait.get("satisfied") is not True or wait.get("status") != "running":
                raise RuntimeError("ORCA worker terminal did not reach TUI readiness")
            # Codex can report an initial idle frame while its MCP servers are still
            # loading.  Require a short stable-idle window before capability input.
            time.sleep(15)
            stable = self._json_command(
                ("terminal", "wait", "--terminal", handle, "--for", "tui-idle",
                 "--timeout-ms", str(timeout_ms), "--json"),
                stage_id="implementation", access="write",
            )
            stable_wait = stable.get("result", {}).get("wait", {})
            if (
                not isinstance(stable_wait, dict)
                or stable_wait.get("satisfied") is not True
                or stable_wait.get("status") != "running"
            ):
                raise RuntimeError("ORCA worker terminal did not remain stably idle")
            dispatched = self._dispatch_to_ready_terminal(
                task_id=task_id, terminal_handle=handle, coordinator_handle=coordinator_handle,
            )
            dispatch_id = dispatched.get("result", {}).get("dispatch", {}).get("id")
            if not isinstance(dispatch_id, str) or not dispatch_id:
                raise RuntimeError("ORCA dispatch returned no dispatch id")
            self.dispatch_bindings[task_id] = (handle, dispatch_id)
        except Exception:
            self.close_terminal_verified(handle=handle, stage_id="implementation")
            raise
        return {"terminal_handle": handle, "dispatch": dispatched}

    def await_settlement(
        self, *, task_id: str, terminal_handle: str, timeout_seconds: int = 300
    ) -> dict[str, Any]:
        """Wait for capability-bound completion, acknowledge delivery, and close the worker."""
        self._assert_ready()
        self._assert_bound()
        if not task_id or not terminal_handle or timeout_seconds <= 0:
            raise ValueError("settlement requires task/terminal identity and positive timeout")
        binding = self.dispatch_bindings.get(task_id)
        if binding is None or binding[0] != terminal_handle:
            raise PermissionError("task and worker terminal are not bound to the same ORCA Dispatch")
        deadline = time.monotonic() + timeout_seconds
        dispatch: dict[str, Any] = {}
        try:
            while time.monotonic() < deadline:
                shown = self.inspect_dispatch(task_id=task_id)
                dispatch = shown.get("result", {}).get("dispatch", {})
                if isinstance(dispatch, dict) and dispatch.get("status") in {"completed", "failed"}:
                    break
                terminal = self._json_command(
                    ("terminal", "show", "--terminal", terminal_handle, "--json"),
                    stage_id="implementation", allowed_error_codes=("terminal_handle_stale",),
                )
                if terminal.get("ok") is False:
                    raise RuntimeError("ORCA worker terminal became stale before settlement")
                if terminal.get("result", {}).get("terminal", {}).get("connected") is False:
                    raise RuntimeError("ORCA worker disconnected before settlement")
                time.sleep(2)
            if dispatch.get("status") != "completed":
                raise RuntimeError(f"ORCA dispatch did not complete: {dispatch.get('status')}")
            if not isinstance(dispatch.get("capability_hash"), str) or not dispatch.get("capability_hash"):
                raise RuntimeError("completed ORCA Dispatch has no capability hash")
            if dispatch.get("failure_count") != 0 or not dispatch.get("capability_revoked_at"):
                raise RuntimeError("completed ORCA Dispatch failed capability settlement invariants")
            delivery = self._json_command(
                ("orchestration", "check", "--run", self.run_id or "", "--terminal",
                 self.coordinator_handle or "", "--json"),
                stage_id="implementation", access="write",
            )
            delivery_id = delivery.get("result", {}).get("deliveryId")
            messages = delivery.get("result", {}).get("messages", [])
            if not isinstance(delivery_id, str) or not isinstance(messages, list):
                raise RuntimeError("ORCA worker_done delivery missing")
            dispatch_id = dispatch.get("id")
            if dispatch_id != binding[1]:
                raise PermissionError("settled Dispatch does not match the bound Dispatch")
            matched = False
            for message in messages:
                if not isinstance(message, dict) or message.get("type") != "worker_done":
                    continue
                try:
                    payload = json.loads(str(message.get("payload", "{}")))
                except json.JSONDecodeError:
                    continue
                matched = payload.get("taskId") == task_id and payload.get("dispatchId") == dispatch_id and payload.get("outcome") == "succeeded"
                if matched:
                    break
            if not matched:
                raise RuntimeError("ORCA delivery does not match the completed Dispatch")
            acknowledged = self._json_command(
                ("orchestration", "check", "--run", self.run_id or "", "--terminal",
                 self.coordinator_handle or "", "--ack", delivery_id, "--json"),
                stage_id="implementation", access="write",
            )
            return {"dispatch": dispatch, "delivery": delivery, "acknowledged": acknowledged}
        finally:
            self.close_terminal_verified(handle=terminal_handle, stage_id="documentation")
            self.dispatch_bindings.pop(task_id, None)

    def create_coordinator_terminal(self, *, title: str = "benchmark-orca-coordinator") -> str:
        selector = self._workspace_selector()
        created = self._json_command(
            ("terminal", "create", "--worktree", selector, "--title", title,
             "--command", "zsh", "--json"), stage_id="intake", access="write",
        )
        handle = created.get("result", {}).get("terminal", {}).get("handle")
        if not isinstance(handle, str) or not handle:
            raise RuntimeError("ORCA coordinator terminal creation returned no handle")
        return handle

    def close_terminal_verified(self, *, handle: str, stage_id: str) -> None:
        self._json_command(
            ("terminal", "close", "--terminal", handle, "--json"),
            stage_id=stage_id, access="write",
        )
        for _ in range(120):
            shown = self._json_command(
                ("terminal", "show", "--terminal", handle, "--json"),
                stage_id=stage_id, allowed_error_codes=("terminal_handle_stale",),
            )
            disconnected = shown.get("result", {}).get("terminal", {}).get("connected") is False
            stale = shown.get("ok") is False and shown.get("error", {}).get("code") == "terminal_handle_stale"
            if disconnected or stale:
                return
            time.sleep(0.25)
        raise RuntimeError("ORCA terminal cleanup could not be verified")

    def inspect_dispatch(self, *, task_id: str) -> dict[str, Any]:
        self._assert_ready()
        return self._json_command(
            ("orchestration", "dispatch-show", "--task", task_id, "--json"),
            stage_id="implementation",
        )

    def assert_ready(self) -> None:
        self._assert_ready()

    def record_lifecycle(
        self, *, stage_id: str, actor: str, status: str,
        duration_ms: float = 0, event_name: str = "stage",
    ) -> dict[str, object]:
        self._assert_ready()
        return self.lifecycle.record(
            stage_id=stage_id, actor=actor, status=status,
            duration_ms=duration_ms, event_name=event_name,
        )

    def record_blocked_attempt(
        self, *, stage_id: str, actor: str, event_name: str = "adapter.not-ready",
    ) -> dict[str, object]:
        return self.lifecycle.record(
            stage_id=stage_id, actor=actor, status="blocked", event_name=event_name,
        )

    def record_external_event(
        self, event: dict[str, object], *, stage_id: str, actor: str,
        parent_event_id: str | None = None,
    ) -> dict[str, object]:
        self._assert_ready()
        return self.lifecycle.record_external(
            event, stage_id=stage_id, actor=actor, parent_event_id=parent_event_id,
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

    def _assert_bound(
        self, *, run_id: str | None = None, coordinator_handle: str | None = None
    ) -> None:
        if self.run_id is None or self.coordinator_handle is None:
            raise RuntimeError("ORCA adapter has no bound Run/coordinator")
        if run_id is not None and run_id != self.run_id:
            raise PermissionError("run id does not match the bound ORCA Run")
        if coordinator_handle is not None and coordinator_handle != self.coordinator_handle:
            raise PermissionError("coordinator handle does not match the bound ORCA coordinator")

    def _workspace_selector(self) -> str:
        current = self._json_command(("worktree", "current", "--json"), stage_id="intake")
        worktree = current.get("result", {}).get("worktree", {})
        identifier = worktree.get("id") if isinstance(worktree, dict) else None
        path = worktree.get("path") if isinstance(worktree, dict) else None
        if not isinstance(identifier, str) or Path(str(path)).resolve() != self.runtime.workspace:
            raise RuntimeError("ORCA current worktree does not match the adapter workspace")
        return f"id:{identifier}"

    def _json_command(
        self,
        args: tuple[str, ...],
        *,
        stage_id: str,
        access: str = "read",
        allowed_error_codes: tuple[str, ...] = (),
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
        ok = parsed.get("ok")
        if not isinstance(ok, bool):
            raise RuntimeError(f"ORCA response has no boolean ok field: {args[0]}")
        error_code = parsed.get("error", {}).get("code") if isinstance(parsed.get("error"), dict) else None
        allowed_failure = ok is False and isinstance(error_code, str) and error_code in allowed_error_codes
        if (result.returncode != 0 or ok is False) and not allowed_failure:
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
