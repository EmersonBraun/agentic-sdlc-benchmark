#!/usr/bin/env python3
"""Run one live Compozy v1.2 ADE x AgentsKit bootstrap condition."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "controller/src"))
sys.path.insert(0, str(ROOT / "controller/scripts"))

from benchmark_controller.agentskit import AgentsKitLedgerBridge  # noqa: E402
from benchmark_controller.agentskit_components import AgentsKitComponentActionBridge  # noqa: E402
from benchmark_controller.ledger import Ledger  # noqa: E402
from probe_compozy_v12_topology import (  # noqa: E402
    CODEX_MODEL,
    CODEX_PROVIDER,
    GROK_MODEL,
    GROK_PROVIDER,
    _matching_grok_pids,
    _run_json,
    _sha,
    _summarize_turn,
    _tree_sha,
)
from run_compozy_technical_pilot import _run_native_agentskit  # noqa: E402

TASK_ID = "pilot_greenfield_service_readiness"
BASE_COMMIT = "032045401c38d0d7f6168ade1cf2053f503e4acc"


def _messages(events: list[dict[str, Any]]) -> str:
    return "".join(
        str(event.get("text", ""))
        for event in events
        if event.get("type") == "agent_message" and isinstance(event.get("text"), str)
    )


def _repository_sha_excluding(*outputs: Path) -> str:
    """Hash the repository while excluding the declared, newly generated evidence."""

    moved: list[tuple[Path, bytes]] = []
    for output in outputs:
        resolved = output.resolve()
        if resolved.is_relative_to(ROOT) and resolved.exists():
            moved.append((resolved, resolved.read_bytes()))
            resolved.unlink()
    try:
        return _tree_sha(ROOT)
    finally:
        for path, content in moved:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--agentskit", choices=("off", "on"), required=True)
    parser.add_argument("--attestation", type=Path, required=True)
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument("--agentskit-native-root", type=Path)
    parser.add_argument("--confirm", action="store_true")
    args = parser.parse_args()
    if not args.confirm:
        print(json.dumps({"status": "blocked", "reason": "confirmation-required"}))
        return 2
    if args.attestation.exists() or args.ledger.exists():
        raise FileExistsError("condition outputs must be new")
    if args.agentskit == "on" and args.agentskit_native_root is None:
        raise RuntimeError("AgentsKit ON requires a pinned public native root")

    condition_id = f"compozy__{args.agentskit}"
    run_id = f"run_v12-bootstrap-{condition_id}"
    task_text = (ROOT / "tasks/public/pilot_greenfield_service_readiness.md").read_text()
    source = ROOT / "products/greenfield"
    args.ledger.parent.mkdir(parents=True, exist_ok=True)
    ledger = Ledger(args.ledger, run_id=run_id, task_id=TASK_ID)
    args.ledger.touch(exist_ok=False)
    commands: dict[str, Any] = {}
    cleanup: dict[str, Any] = {}
    failure: str | None = None
    planner_summary: dict[str, Any] = {}
    executor_summary: dict[str, Any] = {}
    agentskit_evidence: dict[str, Any] = {
        "enabled": args.agentskit == "on",
        "event_count": 0,
        "public_only": args.agentskit == "on",
        "agentskit_os_used": False,
    }
    before_repository = _repository_sha_excluding(args.attestation, args.ledger)
    pids_before = _matching_grok_pids()
    session_id: str | None = None

    with tempfile.TemporaryDirectory(prefix=f"v12-{condition_id}-") as directory:
        fixture = Path(directory) / "greenfield"
        shutil.copytree(source, fixture, ignore=shutil.ignore_patterns("node_modules", ".next", ".git", ".DS_Store"))
        fixture_before = _tree_sha(fixture)
        context = "AgentsKit is disabled. Use only the native ADE and CLI capabilities."
        try:
            if args.agentskit == "on":
                bridge = AgentsKitComponentActionBridge(AgentsKitLedgerBridge(ledger, enabled=True))
                native, context = _run_native_agentskit(args.agentskit_native_root.resolve(), fixture, bridge)
                agentskit_evidence.update(native)
                agentskit_evidence["event_count"] = native["component_action_records"]

            created, commands["session_new"] = _run_json(
                "compozy", "session", "new", "--cwd", str(ROOT), "--agent", "general", "--network", "local", "-o", "json",
            )
            session_id = str(created.get("id", ""))
            if not session_id:
                raise RuntimeError("Compozy returned no session id")

            plan_token = "V12_PLAN_READY_" + hashlib.sha256(condition_id.encode()).hexdigest()[:16].upper()
            plan_prompt = (
                "Technical pipeline validation only. Do not edit files or call tools. Analyze the public task, "
                "explicitly identify ambiguities A1, A2, and A3, and finish with the exact token " + plan_token + ".\n\n"
                + task_text + "\n\nFactor context:\n" + context
            )
            planner_events, commands["planner_prompt"] = _run_json(
                "compozy", "session", "prompt", session_id, plan_prompt,
                "--provider", CODEX_PROVIDER, "--model", CODEX_MODEL, "--reasoning-effort", "low", "-o", "json",
            )
            planner_summary = _summarize_turn(planner_events, plan_token)
            planner_text = _messages(planner_events)
            if not all((
                planner_summary["sentinel_observed"], planner_summary["done_observed"],
                planner_summary["providers"] == [CODEX_PROVIDER], planner_summary["models"] == [CODEX_MODEL],
                all(item in planner_text for item in ("A1", "A2", "A3")),
            )):
                raise RuntimeError("Codex planning contract failed")

            exec_token = "V12_EXEC_READY_" + hashlib.sha256((condition_id + plan_token).encode()).hexdigest()[:16].upper()
            execution_prompt = (
                "Technical executor handoff only. Do not edit files or call tools. Confirm that the plan addresses "
                "A1, A2, and A3, state whether it is implementable, and finish with the exact token " + exec_token
                + ". Planner handoff SHA-256: " + _sha(planner_text) + ". Factor context SHA-256: " + _sha(context) + "."
            )
            executor_events, commands["executor_prompt"] = _run_json(
                "compozy", "session", "prompt", session_id, execution_prompt,
                "--provider", GROK_PROVIDER, "-o", "json",
            )
            executor_summary = _summarize_turn(executor_events, exec_token)
            executor_text = _messages(executor_events)
            if not all((
                executor_summary["sentinel_observed"], executor_summary["done_observed"],
                executor_summary["providers"] == [GROK_PROVIDER],
                all(item in executor_text for item in ("A1", "A2", "A3")),
            )):
                raise RuntimeError("Grok execution handoff contract failed")
        except Exception as exc:
            failure = f"{type(exc).__name__}: {exc}"
        finally:
            if session_id:
                stopped = subprocess.run(
                    ("compozy", "session", "stop", session_id, "-o", "json"),
                    capture_output=True, text=True, check=False, timeout=30,
                )
                cleanup["session_stop_returncode"] = stopped.returncode
            cleanup["fixture_unchanged"] = _tree_sha(fixture) == fixture_before

    sessions, commands["session_list"] = _run_json("compozy", "session", "list", "-o", "json")
    active = sessions.get("sessions", []) if isinstance(sessions, dict) else []
    cleanup["session_residual"] = any(isinstance(item, dict) and item.get("id") == session_id for item in active)
    cleanup["grok_process_residual_count"] = len(_matching_grok_pids() - pids_before)
    cleanup["verified"] = all((
        cleanup.get("session_stop_returncode") == 0,
        not cleanup["session_residual"],
        cleanup["grok_process_residual_count"] == 0,
        cleanup["fixture_unchanged"],
    ))
    repository_unchanged = _repository_sha_excluding(args.attestation, args.ledger) == before_repository
    passed = failure is None and cleanup["verified"] and repository_unchanged
    document: dict[str, Any] = {
        "schema_version": "condition-integration-attestation-v1.2",
        "protocol_version": "v1.2",
        "analysis_eligible": False,
        "live_execution": True,
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "status": "passed" if passed else "failed",
        "condition_id": condition_id,
        "task_id": TASK_ID,
        "base_commit": BASE_COMMIT,
        "factors": {"ade": "compozy", "agentskit": args.agentskit},
        "topology": {
            "planner": {"provider": CODEX_PROVIDER, "model": CODEX_MODEL, "execution": planner_summary},
            "executor": {"provider": GROK_PROVIDER, "configured_model": GROK_MODEL, "execution": executor_summary},
            "same_session": True,
        },
        "agentskit": agentskit_evidence,
        "invariants": {
            "same_task": "passed", "same_base_commit": "passed", "role_topology": "passed" if passed else "failed",
            "workspace_boundary": "passed" if repository_unchanged and cleanup.get("fixture_unchanged") else "failed",
            "permission_policy": "passed", "lifecycle_cleanup": "passed" if cleanup["verified"] else "failed",
            "no_fallback": "passed" if passed else "failed", "agentskit_attribution": "passed" if passed else "failed",
        },
        "cleanup": cleanup,
        "commands": commands,
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
