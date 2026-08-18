#!/usr/bin/env python3
"""Run one live ORCA v1.2 ADE x AgentsKit bootstrap condition."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "controller/src"))
sys.path.insert(0, str(ROOT / "controller/scripts"))

from benchmark_controller.agentskit import AgentsKitLedgerBridge  # noqa: E402
from benchmark_controller.agentskit_components import AgentsKitComponentActionBridge  # noqa: E402
from benchmark_controller.ledger import Ledger  # noqa: E402
from benchmark_controller.orca import OrcaAdapter  # noqa: E402
from probe_compozy_v12_condition import (  # noqa: E402
    BASE_COMMIT, TASK_ID, _repository_sha_excluding,
)
from probe_orca_grok_v12 import EXPECTED_ORCA_VERSION, _nested, _sha, _terminal_handles  # noqa: E402
from run_compozy_technical_pilot import _run_native_agentskit  # noqa: E402


class EvidenceOrcaAdapter(OrcaAdapter):
    """Expose only ORCA's structured error code when a probe command fails."""

    def _json_command(
        self, args: tuple[str, ...], *, stage_id: str, access: str = "read",
        allowed_error_codes: tuple[str, ...] = (),
    ) -> dict[str, Any]:
        result = self.runtime.run(
            (self.cli_path, *args), stage_id=stage_id, actor="infrastructure",
            access=access, time_category="orchestration_overhead",
        )
        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"ORCA returned non-JSON output: {args[0]}") from exc
        if not isinstance(payload, dict) or not isinstance(payload.get("ok"), bool):
            raise RuntimeError(f"ORCA returned unexpected JSON: {args[0]}")
        error = payload.get("error", {}) if isinstance(payload.get("error"), dict) else {}
        code = error.get("code") if isinstance(error.get("code"), str) else None
        allowed = payload["ok"] is False and code in allowed_error_codes
        if (result.returncode != 0 or payload["ok"] is False) and not allowed:
            raise RuntimeError(f"ORCA command failed: {args[0]}:{code or 'unknown'}")
        return payload


def _settlement_summary(value: dict[str, Any]) -> dict[str, Any]:
    dispatch = value["dispatch"]
    delivery = value["delivery"]
    return {
        "status": dispatch.get("status"),
        "failure_count": dispatch.get("failure_count"),
        "capability_hash_present": bool(dispatch.get("capability_hash")),
        "capability_revoked": bool(dispatch.get("capability_revoked_at")),
        "worker_done_accepted": any(
            isinstance(item, dict) and item.get("type") == "worker_done"
            for item in (_nested(delivery, "result", "messages") or [])
        ),
        "delivery_acknowledged": _nested(value["acknowledged"], "ok") is True,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--agentskit", choices=("off", "on"), required=True)
    parser.add_argument("--attestation", type=Path, required=True)
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument("--agentskit-native-root", type=Path)
    parser.add_argument("--confirm", action="store_true")
    parser.add_argument("--allow-host-control", action="store_true")
    parser.add_argument("--timeout-seconds", type=int, default=420)
    args = parser.parse_args()
    if not args.confirm or not args.allow_host_control:
        print(json.dumps({"status": "blocked", "reason": "authorization-required"}))
        return 2
    if args.attestation.exists() or args.ledger.exists():
        raise FileExistsError("condition outputs must be new")
    if args.agentskit == "on" and args.agentskit_native_root is None:
        raise RuntimeError("AgentsKit ON requires a pinned public native root")

    condition_id = f"orca__{args.agentskit}"
    run_id = f"run_v12-bootstrap-{condition_id}"
    args.ledger.parent.mkdir(parents=True, exist_ok=True)
    ledger = Ledger(args.ledger, run_id=run_id, task_id=TASK_ID)
    before_repository = _repository_sha_excluding(args.attestation, args.ledger)
    agentskit_evidence: dict[str, Any] = {
        "enabled": args.agentskit == "on", "event_count": 0,
        "public_only": args.agentskit == "on", "agentskit_os_used": False,
    }
    context = "AgentsKit is disabled. Use only native ORCA and CLI capabilities."
    coordinator: str | None = None
    workers: set[str] = set()
    baseline: set[str] = set()
    planner: dict[str, Any] = {}
    executor: dict[str, Any] = {}
    cleanup: dict[str, Any] = {}
    failure: str | None = None

    with tempfile.TemporaryDirectory(prefix=f"v12-{condition_id}-") as directory:
        fixture = Path(directory) / "greenfield"
        subprocess.run(
            ("cp", "-R", str(ROOT / "products/greenfield"), str(fixture)),
            check=True, capture_output=True,
        )
        try:
            if args.agentskit == "on":
                bridge = AgentsKitComponentActionBridge(AgentsKitLedgerBridge(ledger, enabled=True))
                native, context = _run_native_agentskit(args.agentskit_native_root.resolve(), fixture, bridge)
                agentskit_evidence.update(native)
                agentskit_evidence["event_count"] = native["component_action_records"]

            adapter = EvidenceOrcaAdapter(ROOT, ledger, permission_mode="approve-all")
            status = adapter._json_command(("status", "--json"), stage_id="intake")
            if (
                _nested(status, "result", "runtime", "state") != "ready"
                or _nested(status, "result", "graph", "state") != "ready"
                or _nested(status, "result", "runtime", "appVersion") != EXPECTED_ORCA_VERSION
            ):
                raise RuntimeError("ORCA runtime does not match the frozen ready state")
            baseline = _terminal_handles(adapter)
            coordinator = adapter.create_coordinator_terminal(title=f"v12-{args.agentskit}-coordinator")
            run = adapter.start_workflow(objective=f"v1.2 {condition_id} technical integration", coordinator_handle=coordinator)
            orca_run_id = _nested(run, "result", "run", "id")
            if not isinstance(orca_run_id, str):
                raise RuntimeError("ORCA run identity missing")

            task_text = (ROOT / "tasks/public/pilot_greenfield_service_readiness.md").read_text()
            planner_task = adapter.create_task(
                run_id=orca_run_id, coordinator_handle=coordinator, title="Codex requirements plan",
                spec=(
                    "Read-only technical pilot. Do not edit files. Analyze the task and explicitly address A1, A2, "
                    "and A3. Context SHA-256 is " + _sha(context) + ". Report a concise implementable plan and "
                    "settle this Dispatch with worker_done exactly once. Public task:\n" + task_text
                ),
            )
            planner_task_id = _nested(planner_task, "result", "task", "id")
            started = adapter.start_ready_dispatch(
                task_id=planner_task_id, coordinator_handle=coordinator,
                agent_command="codex --model gpt-5.4 --ask-for-approval never",
                title=f"v12-{args.agentskit}-codex-planner",
            )
            workers.add(str(started["terminal_handle"]))
            settled = adapter.await_settlement(
                task_id=planner_task_id, terminal_handle=str(started["terminal_handle"]), timeout_seconds=args.timeout_seconds,
            )
            workers.discard(str(started["terminal_handle"]))
            planner = _settlement_summary(settled)

            executor_task = adapter.create_task(
                run_id=orca_run_id, coordinator_handle=coordinator, title="Grok implementation assessment",
                spec=(
                    "Read-only technical executor handoff. Do not edit files. The Codex requirements Dispatch "
                    "completed successfully. Confirm A1, A2, and A3 are implementable under the same task and factor "
                    "context SHA-256 " + _sha(context) + ", then settle this Dispatch with worker_done exactly once."
                ),
            )
            executor_task_id = _nested(executor_task, "result", "task", "id")
            started = adapter.start_ready_dispatch(
                task_id=executor_task_id, coordinator_handle=coordinator,
                agent_command="grok --model grok-4.5 --reasoning-effort high --always-approve",
                title=f"v12-{args.agentskit}-grok-executor",
            )
            workers.add(str(started["terminal_handle"]))
            settled = adapter.await_settlement(
                task_id=executor_task_id, terminal_handle=str(started["terminal_handle"]), timeout_seconds=args.timeout_seconds,
            )
            workers.discard(str(started["terminal_handle"]))
            executor = _settlement_summary(settled)
        except Exception as exc:
            failure = f"{type(exc).__name__}: {exc}"
        finally:
            if "adapter" in locals():
                for handle in [*workers, coordinator]:
                    if handle:
                        try:
                            adapter.close_terminal_verified(handle=handle, stage_id="documentation")
                        except Exception as exc:
                            failure = failure or f"{type(exc).__name__}: cleanup failed"
                residual = _terminal_handles(adapter) - baseline
                cleanup = {"terminal_residual_count": len(residual), "verified": not residual}

    repository_unchanged = _repository_sha_excluding(args.attestation, args.ledger) == before_repository
    topology_passed = all(
        item.get("status") == "completed"
        and item.get("failure_count") == 0
        and item.get("capability_hash_present")
        and item.get("capability_revoked")
        and item.get("worker_done_accepted")
        and item.get("delivery_acknowledged")
        for item in (planner, executor)
    )
    passed = failure is None and topology_passed and cleanup.get("verified") is True and repository_unchanged
    document: dict[str, Any] = {
        "schema_version": "condition-connectivity-smoke-attestation-v1.2",
        "protocol_version": "v1.2", "analysis_eligible": False, "live_connectivity_execution": True,
        "semantic_parity_eligible": False,
        "scope": "live ADE/provider connectivity smoke; not a full SDLC condition run",
        "missing_gates": ["frozen_base_worktree", "full_sdlc", "complete_ade_ledger", "agentskit_inside_ade", "permission_parity", "independent_evaluation"],
        "observed_at": datetime.now(timezone.utc).isoformat(), "status": "passed" if passed else "failed",
        "condition_id": condition_id, "task_id": TASK_ID, "base_commit": BASE_COMMIT,
        "factors": {"ade": "orca", "agentskit": args.agentskit},
        "topology": {
            "planner": {"provider": "codex-cli", "model": "gpt-5.4", "settlement": planner},
            "executor": {"provider": "grok-cli", "model": "grok-4.5", "settlement": executor},
            "sequential_capability_bound_dispatches": True,
        },
        "agentskit": agentskit_evidence, "cleanup": cleanup,
        "invariants": {
            "same_task": "passed", "same_base_commit": "not_evaluated",
            "role_topology": "passed" if topology_passed else "failed",
            "workspace_boundary": "passed" if repository_unchanged else "failed",
            "permission_policy": "not_evaluated", "lifecycle_cleanup": "passed" if cleanup.get("verified") else "failed",
            "no_fallback": "passed" if topology_passed else "failed",
            "agentskit_attribution": "component_executed_not_integrated" if args.agentskit == "on" else "not_applicable",
        },
        "ledger_sha256": _sha(args.ledger.read_bytes()),
        "redaction": {"raw_prompts_persisted_publicly": False, "raw_outputs_persisted_publicly": False},
        "source_hashes": {"probe": _sha(Path(__file__).read_bytes())},
    }
    if failure:
        document["failure"] = failure
    args.attestation.parent.mkdir(parents=True, exist_ok=True)
    args.attestation.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"status": document["status"], "condition_id": condition_id, "sha256": _sha(args.attestation.read_bytes())}))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
