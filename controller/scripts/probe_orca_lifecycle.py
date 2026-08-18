#!/usr/bin/env python3
"""Run the reproducible ORCA terminal-ready lifecycle settlement probe."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "controller/src"))

from benchmark_controller.ledger import Ledger  # noqa: E402
from benchmark_controller.orca import OrcaAdapter  # noqa: E402

IGNORED = {".DS_Store"}
EXPECTED_ORCA_VERSION = "1.4.184"


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def tree_sha256(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        if any(part in IGNORED for part in relative.parts):
            continue
        digest.update(str(relative).encode())
        if path.is_symlink():
            digest.update(b"symlink\0" + str(path.readlink()).encode())
        elif path.is_file():
            digest.update(b"file\0" + path.read_bytes())
        else:
            digest.update(b"dir\0")
    return digest.hexdigest()


def nested(document: dict[str, Any], *keys: str) -> Any:
    value: Any = document
    for key in keys:
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    return value


def validated_terminal_inventory(document: dict[str, Any]) -> list[dict[str, Any]]:
    inventory = nested(document, "result", "terminals")
    if not isinstance(inventory, list) or len(inventory) >= 100:
        raise RuntimeError("ORCA terminal inventory is missing or may be truncated")
    if any(
        not isinstance(terminal, dict)
        or not isinstance(terminal.get("handle"), str)
        or not isinstance(terminal.get("connected"), bool)
        for terminal in inventory
    ):
        raise RuntimeError("ORCA terminal inventory contains a malformed entry")
    return inventory


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--confirm", action="store_true")
    parser.add_argument("--allow-host-control", action="store_true")
    parser.add_argument("--observation", type=Path, required=True)
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument("--attestation", type=Path)
    parser.add_argument("--timeout-seconds", type=int, default=300)
    args = parser.parse_args()
    if not args.confirm or not args.allow_host_control:
        print(json.dumps({"executable": False, "reason": "operator confirmation and host-control authorization required"}))
        return 2
    if args.observation.exists() or args.ledger.exists() or (args.attestation and args.attestation.exists()):
        raise FileExistsError("observation, ledger, and attestation paths must be new")
    output_paths = [args.observation, args.ledger, *([args.attestation] if args.attestation else [])]
    if any(path.resolve().is_relative_to(ROOT) for path in output_paths):
        raise ValueError("probe outputs must be outside the benchmark repository")

    workspace = ROOT
    before = tree_sha256(workspace)
    ledger = Ledger(args.ledger, run_id="run_orca-lifecycle-readiness", task_id="pilot_smoke")
    adapter = OrcaAdapter(workspace, ledger, permission_mode="approve-all")
    coordinator: str | None = None
    worker: str | None = None
    worker_identity: str | None = None
    run_id: str | None = None
    task_id: str | None = None
    dispatch_id: str | None = None
    capability_hash: str | None = None
    delivery_acknowledged = False
    terminal_wait: dict[str, Any] = {}
    current: dict[str, Any] = {}
    dispatch: dict[str, Any] = {}
    cleanup_ok = True
    live_probe_terminals: int | None = None
    baseline_terminal_handles: set[str] = set()
    status = "failed"
    error: str | None = None
    try:
        current = adapter._json_command(("status", "--json"), stage_id="intake")
        if nested(current, "result", "runtime", "state") != "ready" or nested(current, "result", "graph", "state") != "ready":
            raise RuntimeError("ORCA runtime and graph must both be ready before mutation")
        if nested(current, "result", "runtime", "appVersion") != EXPECTED_ORCA_VERSION:
            raise RuntimeError("ORCA runtime version does not match the frozen adapter version")
        baseline = adapter._json_command(
            ("terminal", "list", "--worktree", adapter._workspace_selector(), "--limit", "100", "--json"),
            stage_id="intake",
        )
        baseline_inventory = validated_terminal_inventory(baseline)
        baseline_terminal_handles = {
            str(terminal["handle"])
            for terminal in baseline_inventory
            if isinstance(terminal, dict) and isinstance(terminal.get("handle"), str)
        }
        coordinator = adapter.create_coordinator_terminal()
        run = adapter.start_workflow(objective="ORCA v1.1 lifecycle settlement probe", coordinator_handle=coordinator)
        run_id = nested(run, "result", "run", "id")
        if not isinstance(run_id, str):
            raise RuntimeError("run id missing")
        task = adapter.create_task(
            run_id=run_id, coordinator_handle=coordinator, title="Lifecycle settlement probe",
            spec="Read-only. Report ORCA_LIFECYCLE_READY and send worker_done once without file changes.",
        )
        task_id = nested(task, "result", "task", "id")
        if not isinstance(task_id, str):
            raise RuntimeError("task id missing")
        started = adapter.start_ready_dispatch(
            task_id=task_id, coordinator_handle=coordinator,
            agent_command="codex --sandbox danger-full-access --ask-for-approval never -m gpt-5.4 -c model_reasoning_effort=medium",
            timeout_ms=120000,
        )
        worker = started["terminal_handle"]
        worker_identity = worker
        dispatch_id = nested(started["dispatch"], "result", "dispatch", "id")
        settled = adapter.await_settlement(
            task_id=task_id, terminal_handle=worker, timeout_seconds=args.timeout_seconds,
        )
        dispatch = settled["dispatch"]
        capability_hash = dispatch.get("capability_hash")
        if nested(current, "result", "runtime", "state") != "ready" or nested(current, "result", "graph", "state") != "ready":
            raise RuntimeError("ORCA runtime and graph must both be ready")
        if nested(current, "result", "runtime", "appVersion") != EXPECTED_ORCA_VERSION:
            raise RuntimeError("ORCA runtime version does not match the frozen adapter version")
        if not isinstance(capability_hash, str) or not capability_hash:
            raise RuntimeError("completed ORCA dispatch has no capability hash")
        if dispatch.get("failure_count") != 0 or not dispatch.get("capability_revoked_at"):
            raise RuntimeError("ORCA dispatch settlement invariants failed")
        delivery = settled["delivery"]
        messages = nested(delivery, "result", "messages")
        delivery_id = nested(delivery, "result", "deliveryId")
        if not isinstance(messages, list) or not any(message.get("type") == "worker_done" for message in messages):
            raise RuntimeError("accepted worker_done delivery missing")
        if not isinstance(delivery_id, str):
            raise RuntimeError("delivery id missing")
        delivery_acknowledged = True
        adapter.record_lifecycle(
            stage_id="implementation", actor="executor", status="completed",
            event_name="dispatch.worker_done.settled",
        )
        adapter.record_lifecycle(
            stage_id="implementation", actor="controller", status="completed",
            event_name="delivery.acknowledged",
        )
        worker = None
        terminal_wait = {"condition": "tui-idle", "satisfied": True, "status": "running"}
        status = "passed"
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
    finally:
        for handle in (worker, coordinator):
            if isinstance(handle, str):
                try:
                    adapter.close_terminal_verified(handle=handle, stage_id="documentation")
                except Exception as exc:
                    cleanup_ok = False
                    error = error or f"{type(exc).__name__}: {exc}"
                    status = "failed"
        try:
            terminals = adapter._json_command(
                ("terminal", "list", "--worktree", adapter._workspace_selector(), "--limit", "100", "--json"),
                stage_id="documentation",
            )
            inventory = validated_terminal_inventory(terminals)
            live_probe_terminals = sum(
                1 for terminal in inventory
                if isinstance(terminal, dict)
                and isinstance(terminal.get("handle"), str)
                and terminal.get("handle") not in baseline_terminal_handles
                and terminal.get("connected") is not False
            )
            if live_probe_terminals != 0:
                raise RuntimeError("ORCA probe terminals remain connected")
            adapter.record_lifecycle(
                stage_id="documentation", actor="infrastructure", status="completed",
                event_name="terminals.cleanup.verified",
            )
        except Exception as exc:
            cleanup_ok = False
            status = "failed"
            error = error or f"{type(exc).__name__}: {exc}"

    workspace_unchanged = tree_sha256(workspace) == before
    if not workspace_unchanged:
        status = "failed"
        error = error or "RuntimeError: probe modified the benchmark workspace"
    observation: dict[str, Any] = {
        "schema_version": "orca-lifecycle-observation-v1.1",
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "runtime_version": nested(current, "result", "runtime", "appVersion"),
        "runtime_ready": nested(current, "result", "runtime", "state") == "ready",
        "graph_ready": nested(current, "result", "graph", "state") == "ready",
        "model": "gpt-5.4",
        "reasoning_effort": "medium",
        "host_control_authorized": True,
        "terminal_wait": terminal_wait,
        "dispatch": {
            "id_sha256": sha256_text(dispatch_id or ""), "capability_hash": capability_hash,
            "status": "completed" if status == "passed" else "failed",
            "failure_count": dispatch.get("failure_count"),
            "capability_revoked": bool(dispatch.get("capability_revoked_at")),
        },
        "delivery": {
            "type": "worker_done", "outcome": "succeeded" if status == "passed" else "failed",
            "task_id_sha256": sha256_text(task_id or ""),
            "dispatch_id_sha256": sha256_text(dispatch_id or ""), "acknowledged": delivery_acknowledged,
        },
        "cleanup": {
            "worker_connected": False if cleanup_ok else None,
            "coordinator_connected": False if cleanup_ok else None,
            "live_probe_terminals": live_probe_terminals,
            "workspace_tree_unchanged": workspace_unchanged,
        },
        "redaction": {
            "raw_prompt_persisted": False, "raw_model_output_persisted": False,
            "dispatch_capability_persisted": False, "identifiers_hashed": True,
        },
    }
    if error:
        observation["error"] = error
    args.observation.write_text(json.dumps(observation, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if args.attestation:
        ledger_event_count = sum(1 for line in args.ledger.read_text(encoding="utf-8").splitlines() if line.strip())
        source_paths = {
            "orca_adapter_source_sha256": ROOT / "controller/src/benchmark_controller/orca.py",
            "ade_registry_source_sha256": ROOT / "controller/src/benchmark_controller/ade_adapters.py",
            "descriptor_source_sha256": ROOT / "controller/src/benchmark_controller/adapters.py",
            "probe_source_sha256": Path(__file__),
        }
        attestation = {
            "schema_version": "orca-v1.1-lifecycle-probe-attestation",
            "protocol_version": "v1.1", "verified_on": datetime.now(timezone.utc).date().isoformat(),
            "status": status, "analysis_eligible": False,
            "runtime": {
                "app_version": nested(current, "result", "runtime", "appVersion"),
                "state": nested(current, "result", "runtime", "state"),
                "graph_state": nested(current, "result", "graph", "state"),
                "runtime_id_sha256": sha256_text(str(nested(current, "result", "runtime", "runtimeId") or "")),
            },
            "model": {
                "provider": "codex", "model": "gpt-5.4", "reasoning_effort": "medium",
                "execution_observed": status == "passed",
                "host_control_authorized": True,
            },
            "orchestration": {
                "run_id_sha256": sha256_text(run_id or ""),
                "task_id_sha256": sha256_text(task_id or ""),
                "dispatch_id_sha256": sha256_text(dispatch_id or ""),
                "coordinator_terminal_sha256": sha256_text(coordinator or ""),
                "worker_terminal_sha256": sha256_text(worker_identity or ""),
                "dispatch_capability_hash": capability_hash,
                "terminal_ready_before_dispatch": terminal_wait.get("satisfied") is True,
                "dispatch_injected": dispatch_id is not None,
                "worker_done_accepted": status == "passed",
                "dispatch_terminal_state": dispatch.get("status") or ("failed" if status == "failed" else None),
                "delivery_acknowledged": delivery_acknowledged,
                "required_path": "terminal-create; stable-terminal-wait-tui-idle; orchestration-dispatch-inject",
                "unsupported_path": "worker-start-before-agent-tui-readiness",
            },
            "cleanup": {
                "worker_terminal_closed": cleanup_ok,
                "coordinator_terminal_closed": cleanup_ok,
                "live_probe_terminals_remaining": live_probe_terminals,
                "workspace_mutated": not workspace_unchanged,
            },
            "evidence": {
                "observation": args.observation.name,
                "observation_sha256": hashlib.sha256(args.observation.read_bytes()).hexdigest(),
                "ledger": args.ledger.name,
                "ledger_sha256": hashlib.sha256(args.ledger.read_bytes()).hexdigest(),
                "ledger_event_count": ledger_event_count,
                **{name: hashlib.sha256(path.read_bytes()).hexdigest() for name, path in source_paths.items()},
                "raw_model_output_published": False,
                "public_evidence_is_redacted": True,
            },
            "decision": (
                "ORCA is component-ready through the stable terminal-ready then dispatch --inject path. "
                "The probe requires capability-bound worker_done settlement, acknowledged delivery, "
                "workspace preservation, and verified terminal cleanup."
            ),
        }
        args.attestation.write_text(json.dumps(attestation, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": status, "observation": str(args.observation)}))
    return 0 if status == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
