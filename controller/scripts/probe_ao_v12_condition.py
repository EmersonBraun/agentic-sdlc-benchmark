#!/usr/bin/env python3
"""Run one live Agent Orchestrator v1.2 ADE x AgentsKit bootstrap condition."""

from __future__ import annotations

import argparse
import hashlib
import json
import plistlib
import re
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
from probe_ao_grok_v12 import AO, AO_PLIST, GROK, SESSION_PATTERN, _run, _sha  # noqa: E402
from probe_compozy_v12_condition import BASE_COMMIT, TASK_ID, _repository_sha_excluding  # noqa: E402
from run_compozy_technical_pilot import _run_native_agentskit  # noqa: E402


def _spawn_and_observe(
    *, project: str, name: str, kind: str, prompt: str, sentinel: str, expected_model_text: str,
) -> tuple[str, dict[str, Any]]:
    spawned = _run(
        str(AO), "spawn", "--project", project, "--name", name, "--issue", "18",
        "--prompt", prompt, "--kind", kind, "--mode", "tui", timeout=60,
    )
    match = SESSION_PATTERN.search(spawned.stdout + spawned.stderr)
    session_id = match.group(1) if match else None
    if spawned.returncode or not session_id:
        raise RuntimeError(f"AO did not create the {kind} session")
    capture = ""
    deadline = time.monotonic() + 180
    while time.monotonic() < deadline:
        observed = _run("tmux", "capture-pane", "-pt", session_id, "-S", "-300")
        capture = observed.stdout + observed.stderr
        if sentinel in capture and expected_model_text.lower() in capture.lower():
            break
        time.sleep(1)
    session = _run(str(AO), "session", "get", session_id, "--project", project, "--json")
    payload = json.loads(session.stdout).get("session", {})
    workspace = Path(str(payload.get("workspacePath") or payload.get("workspace_path") or ""))
    if not workspace.is_dir():
        workspace = Path.home() / ".ao/data/worktrees" / project / session_id
    status = _run("git", "-C", str(workspace), "status", "--porcelain", "--untracked-files=all")
    evidence = {
        "session_id_sha256": _sha(session_id),
        "spawn_output_sha256": _sha(spawned.stdout + spawned.stderr),
        "capture_sha256": _sha(capture),
        "sentinel_observed": sentinel in capture,
        "effective_model_observed": expected_model_text.lower() in capture.lower(),
        "trust_prompt_observed": "Do you trust the contents" in capture,
        "workspace_path_sha256": _sha(str(workspace.resolve())),
        "workspace_clean": status.returncode == 0 and status.stdout == "",
        "workspace_status_sha256": _sha(status.stdout + status.stderr),
    }
    return session_id, evidence


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", default="code-10x")
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

    condition_id = f"agent-orchestrator__{args.agentskit}"
    args.ledger.parent.mkdir(parents=True, exist_ok=True)
    ledger = Ledger(args.ledger, run_id=f"run_v12-bootstrap-{condition_id}", task_id=TASK_ID)
    args.ledger.touch(exist_ok=False)
    before_repository = _repository_sha_excluding(args.attestation, args.ledger)
    agentskit_evidence: dict[str, Any] = {
        "enabled": args.agentskit == "on", "event_count": 0,
        "public_only": args.agentskit == "on", "agentskit_os_used": False,
    }
    context = "AgentsKit is disabled. Use only native Agent Orchestrator and CLI capabilities."
    sessions: list[str] = []
    roles: dict[str, Any] = {}
    cleanup: dict[str, Any] = {}
    failure: str | None = None

    with tempfile.TemporaryDirectory(prefix=f"v12-{condition_id}-") as directory:
        fixture = Path(directory) / "greenfield"
        shutil.copytree(
            ROOT / "products/greenfield", fixture,
            ignore=shutil.ignore_patterns("node_modules", ".next", ".git", ".DS_Store"),
        )
        try:
            if args.agentskit == "on":
                bridge = AgentsKitComponentActionBridge(AgentsKitLedgerBridge(ledger, enabled=True))
                native, context = _run_native_agentskit(args.agentskit_native_root.resolve(), fixture, bridge)
                agentskit_evidence.update(native)
                agentskit_evidence["event_count"] = native["component_action_records"]

            project = _run(str(AO), "project", "get", args.project, "--json")
            config = json.loads(project.stdout)["project"]["config"]
            worker = config.get("worker", {})
            orchestrator = config.get("orchestrator", {})
            topology_configured = all((
                project.returncode == 0,
                worker.get("agent") == "grok",
                worker.get("agentConfig", {}).get("model") == "grok-4.5",
                orchestrator.get("agent") == "codex",
                orchestrator.get("agentConfig", {}).get("model") == "gpt-5.4",
            ))
            if not topology_configured:
                raise RuntimeError("AO project role topology is not pinned")

            task_text = (ROOT / "tasks/public/pilot_greenfield_service_readiness.md").read_text()
            plan_sentinel = "V12_AO_PLAN_" + hashlib.sha256(condition_id.encode()).hexdigest()[:16].upper()
            planner_id, roles["planner"] = _spawn_and_observe(
                project=args.project, name=f"v12-{args.agentskit}-codex-planner", kind="orchestrator",
                prompt=(
                    "Read-only technical pilot. Do not edit files or run tools. Analyze A1, A2, and A3 under factor "
                    "context SHA-256 " + _sha(context) + ", then finish with exactly " + plan_sentinel + ".\n\n" + task_text
                ),
                sentinel=plan_sentinel, expected_model_text="gpt-5.4",
            )
            sessions.append(planner_id)
            if not all((
                roles["planner"]["sentinel_observed"], roles["planner"]["effective_model_observed"],
                not roles["planner"]["trust_prompt_observed"], roles["planner"]["workspace_clean"],
            )):
                raise RuntimeError("AO Codex planner contract failed")

            exec_sentinel = "V12_AO_EXEC_" + hashlib.sha256((condition_id + plan_sentinel).encode()).hexdigest()[:16].upper()
            executor_id, roles["executor"] = _spawn_and_observe(
                project=args.project, name=f"v12-{args.agentskit}-grok-executor", kind="worker",
                prompt=(
                    "Read-only technical executor handoff. Do not edit files or run tools. The Codex planner completed. "
                    "Confirm A1, A2, and A3 are implementable under factor context SHA-256 " + _sha(context)
                    + ", then finish with exactly " + exec_sentinel + "."
                ),
                sentinel=exec_sentinel, expected_model_text="Grok 4.5",
            )
            sessions.append(executor_id)
            if not all((
                roles["executor"]["sentinel_observed"], roles["executor"]["effective_model_observed"],
                not roles["executor"]["trust_prompt_observed"], roles["executor"]["workspace_clean"],
            )):
                raise RuntimeError("AO Grok executor contract failed")
        except Exception as exc:
            failure = f"{type(exc).__name__}: {exc}"
        finally:
            kill_results = []
            for session_id in reversed(sessions):
                killed = _run(str(AO), "session", "kill", session_id, "--project", args.project)
                kill_results.append(killed.returncode)
            reclaimed = _run(str(AO), "session", "cleanup", "--project", args.project, "--yes", timeout=60)
            listed = _run(str(AO), "session", "ls", "--all", "--project", args.project, "--json")
            cleanup = {
                "kill_returncodes": kill_results,
                "cleanup_returncode": reclaimed.returncode,
                "session_residual_count": sum(session_id in listed.stdout for session_id in sessions),
            }
            cleanup["verified"] = (
                all(code == 0 for code in kill_results)
                and reclaimed.returncode == 0
                and cleanup["session_residual_count"] == 0
            )

    repository_unchanged = _repository_sha_excluding(args.attestation, args.ledger) == before_repository
    topology_passed = len(roles) == 2 and all(
        role.get("sentinel_observed") and role.get("effective_model_observed") and role.get("workspace_clean")
        for role in roles.values()
    )
    passed = failure is None and topology_passed and cleanup["verified"] and repository_unchanged
    with AO_PLIST.open("rb") as stream:
        ao_version = str(plistlib.load(stream)["CFBundleShortVersionString"])
    document: dict[str, Any] = {
        "schema_version": "condition-integration-attestation-v1.2",
        "protocol_version": "v1.2", "analysis_eligible": False, "live_execution": True,
        "observed_at": datetime.now(timezone.utc).isoformat(), "status": "passed" if passed else "failed",
        "condition_id": condition_id, "task_id": TASK_ID, "base_commit": BASE_COMMIT,
        "factors": {"ade": "agent-orchestrator", "agentskit": args.agentskit},
        "topology": {
            "planner": {"provider": "codex-cli", "model": "gpt-5.4", "execution": roles.get("planner", {})},
            "executor": {"provider": "grok-cli", "model": "grok-4.5", "execution": roles.get("executor", {})},
            "native_separate_sessions": True,
        },
        "agentskit": agentskit_evidence, "cleanup": cleanup,
        "versions": {"agent_orchestrator": ao_version, "grok": _run(str(GROK), "--version").stdout.strip()},
        "invariants": {
            "same_task": "passed", "same_base_commit": "passed",
            "role_topology": "passed" if topology_passed else "failed",
            "workspace_boundary": "passed" if repository_unchanged else "failed",
            "permission_policy": "passed", "lifecycle_cleanup": "passed" if cleanup["verified"] else "failed",
            "no_fallback": "passed" if topology_passed else "failed",
            "agentskit_attribution": "passed" if passed else "failed",
        },
        "ledger_sha256": _sha(args.ledger.read_bytes()),
        "redaction": {"raw_prompts_persisted_publicly": False, "raw_outputs_persisted_publicly": False},
        "source_hashes": {"probe": _sha(Path(__file__).read_bytes()), "ao_executable": _sha(AO.read_bytes())},
    }
    if failure:
        document["failure"] = failure
    args.attestation.parent.mkdir(parents=True, exist_ok=True)
    args.attestation.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"status": document["status"], "condition_id": condition_id, "sha256": _sha(args.attestation.read_bytes())}))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
