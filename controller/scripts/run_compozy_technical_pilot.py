#!/usr/bin/env python3
"""Execute the preregistered Compozy technical pilot into a prepared bundle."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import time
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "controller" / "src"))

from benchmark_controller.compozy_lifecycle import normalize_compozy_events  # noqa: E402
from benchmark_controller.agentskit import AgentsKitLedgerBridge  # noqa: E402
from benchmark_controller.agentskit_components import AgentsKitComponentActionBridge  # noqa: E402
from benchmark_controller.external import LifecycleBridge  # noqa: E402
from benchmark_controller.ledger import Ledger  # noqa: E402
from benchmark_controller.pilot_executor import ConditionedPilotExecutor  # noqa: E402
from benchmark_controller.run_bundles import PreparedRunBundle, RunBundleWriter  # noqa: E402

PUBLIC_NATIVE_COMPONENTS = {
    "doc_bridge": {
        "directory": "doc-bridge",
        "repository": "https://github.com/AgentsKit-io/doc-bridge",
        "commit": "9a03016932b9e3024604712183152025c0577fe4",
    },
    "playbook": {
        "directory": "agents-playbook",
        "repository": "https://github.com/AgentsKit-io/agents-playbook",
        "commit": "0818d860655c2d367f4d8b8c281c9b73ec5adad2",
    },
    "code_review": {
        "directory": "code-review-cli",
        "repository": "https://github.com/AgentsKit-io/code-review-cli",
        "commit": "467cfa570a6b5f1076098b3c76be4e812562f23e",
    },
}


def _sha256(value: str | bytes) -> str:
    data = value.encode("utf-8") if isinstance(value, str) else value
    return hashlib.sha256(data).hexdigest()


def _run(*args: str, timeout: int = 120, cwd: Path | None = None) -> tuple[int, str, float]:
    started = time.monotonic_ns()
    completed = subprocess.run(args, capture_output=True, text=True, check=False, timeout=timeout, cwd=cwd)
    duration_ms = (time.monotonic_ns() - started) / 1_000_000
    return completed.returncode, completed.stdout + completed.stderr, duration_ms


def _json(value: str) -> Any:
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return None


def _session_record(value: str) -> dict[str, Any]:
    payload = _json(value)
    if isinstance(payload, dict) and payload.get("id"):
        return payload
    if isinstance(payload, dict):
        records = payload.get("sessions", payload.get("data", []))
        if isinstance(records, list) and records and isinstance(records[0], dict):
            return records[0]
    return {}


def _events(value: str) -> list[dict[str, Any]]:
    payload = _json(value)
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        records = payload.get("events", payload.get("data", []))
        if isinstance(records, list):
            return [item for item in records if isinstance(item, dict)]
    return []


def _tree_sha256(root: Path) -> str:
    digest = hashlib.sha256()
    files = []
    for item in root.rglob("*"):
        if not item.is_file():
            continue
        relative = item.relative_to(root)
        if relative.parts and relative.parts[0] in {".compozy", ".git"}:
            continue
        files.append(item)
    for path in sorted(files):
        digest.update(path.relative_to(root).as_posix().encode("utf-8"))
        digest.update(path.read_bytes())
    return digest.hexdigest()


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _normalized_repository(value: str) -> str:
    return value.strip().removesuffix(".git").rstrip("/")


def _verify_public_checkout(name: str, source: Path) -> dict[str, Any]:
    expected = PUBLIC_NATIVE_COMPONENTS[name]
    code, revision, _ = _run("git", "rev-parse", "HEAD", cwd=source)
    if code != 0 or revision.strip() != expected["commit"]:
        raise RuntimeError(f"native_{name}_revision_mismatch")
    code, origin, _ = _run("git", "remote", "get-url", "origin", cwd=source)
    if code != 0 or _normalized_repository(origin) != expected["repository"]:
        raise RuntimeError(f"native_{name}_origin_mismatch")
    code, status, _ = _run("git", "status", "--porcelain", cwd=source)
    if code != 0 or status.strip():
        raise RuntimeError(f"native_{name}_working_tree_not_clean")
    return {
        "commit": revision.strip(),
        "repository": expected["repository"],
        "working_tree_clean": True,
        "provenance_verified": True,
    }


def _materialize_public_runtime(name: str, source: Path, executable: Path) -> dict[str, Any]:
    commands = {
        "doc_bridge": (
            ("pnpm", "install", "--frozen-lockfile", "--ignore-scripts"),
            ("pnpm", "build"),
        ),
        "playbook": (
            ("pnpm", "install", "--frozen-lockfile", "--ignore-scripts"),
            ("pnpm", "test:playbook-package"),
        ),
        "code_review": (
            ("npm", "ci", "--ignore-scripts"),
            ("npm", "run", "build"),
        ),
    }[name]
    command_evidence = []
    for command in commands:
        code, output, duration = _run(*command, timeout=600, cwd=source)
        command_evidence.append({
            "argv_sha256": _sha256(json.dumps(command, separators=(",", ":"))),
            "output_sha256": _sha256(output),
            "duration_ms": duration,
            "returncode": code,
        })
        if code != 0:
            raise RuntimeError(f"native_{name}_materialization_failed")
    if not executable.is_file():
        raise RuntimeError(f"native_{name}_executable_missing_after_materialization")
    code, tracked_status, _ = _run("git", "status", "--porcelain", "--untracked-files=no", cwd=source)
    if code != 0 or tracked_status.strip():
        raise RuntimeError(f"native_{name}_materialization_modified_tracked_source")
    return {
        "materialized_from_lockfile": True,
        "executable_sha256": _sha256(executable.read_bytes()),
        "materialization_commands": command_evidence,
    }


def _run_native_agentskit(
    native_root: Path,
    fixture: Path,
    bridge: AgentsKitComponentActionBridge,
) -> tuple[dict[str, Any], str]:
    """Execute the three public component runtimes and retain bounded evidence only."""

    doc_bridge = native_root / PUBLIC_NATIVE_COMPONENTS["doc_bridge"]["directory"]
    playbook = native_root / PUBLIC_NATIVE_COMPONENTS["playbook"]["directory"]
    code_review = native_root / PUBLIC_NATIVE_COMPONENTS["code_review"]["directory"]
    required = (
        doc_bridge / "bin" / "ak-docs.js",
        playbook / "packages" / "playbook" / "bin" / "agents-playbook.mjs",
        code_review / "dist" / "src" / "cli.js",
    )
    components: dict[str, Any] = {}
    for name, source in (("doc_bridge", doc_bridge), ("playbook", playbook), ("code_review", code_review)):
        provenance = _verify_public_checkout(name, source)
        manifest = json.loads((source / "package.json").read_text(encoding="utf-8"))
        executable = {
            "doc_bridge": required[0],
            "playbook": required[1],
            "code_review": required[2],
        }[name]
        materialization = _materialize_public_runtime(name, source, executable)
        components[name] = {**provenance, **materialization, "version": manifest["version"]}

    evidence: dict[str, Any] = {
        "native_external_components_executed": True,
        "components": components,
        "commands": {},
    }

    bridge.record({"component": "doc-bridge", "operation": "lookup", "phase": "start", "stage_id": "requirements"})
    code, output, duration = _run("node", str(required[0]), "demo", "--fixture", "example", "--text", cwd=doc_bridge)
    evidence["commands"]["doc_bridge"] = {"returncode": code, "output_sha256": _sha256(output), "duration_ms": duration}
    if code != 0:
        raise RuntimeError("native_doc_bridge_failed")
    bridge.record({"component": "doc-bridge", "operation": "lookup", "phase": "complete", "durationMs": duration, "stage_id": "requirements"})

    code, output, duration = _run(
        "node", str(required[1]), "run", "error-raw", "--cwd", str(fixture), cwd=playbook,
    )
    evidence["commands"]["playbook"] = {"returncode": code, "output_sha256": _sha256(output), "duration_ms": duration}
    if code != 0:
        raise RuntimeError("native_playbook_failed")
    bridge.record({"component": "playbook", "operation": "step", "phase": "complete", "step": 1, "durationMs": duration, "stage_id": "requirements"})

    bridge.record({"component": "specialized-agents", "operation": "delegate", "phase": "start", "name": "code-review", "depth": 0, "stage_id": "review"})
    code, output, duration = _run(
        "node", str(required[2]), "--provider", "codex-cli", "--model", "gpt-5.4",
        "--paths", "src/app/health/route.ts", "--max-files", "1", "--concurrency", "1",
        "--votes", "1", "--no-fail", timeout=600, cwd=fixture,
    )
    evidence["commands"]["code_review"] = {"returncode": code, "output_sha256": _sha256(output), "duration_ms": duration}
    if code != 0 or "7/7 lens executions succeeded" not in output:
        raise RuntimeError("native_code_review_failed")
    # Delegation and review describe the same wall-clock operation. Keep the
    # delegation lifecycle event at zero duration and attribute work once to
    # the concrete code-review action.
    bridge.record({"component": "specialized-agents", "operation": "delegate", "phase": "complete", "name": "code-review", "depth": 0, "stage_id": "review"})
    bridge.record({"component": "code-review", "operation": "review", "phase": "complete", "durationMs": duration, "stage_id": "review"})

    evidence["component_action_records"] = 6
    context = (
        "\n\nAgentsKit native public-component evidence: Doc Bridge resolved its demo handoff and freshness gate; "
        "the Playbook error-raw quality gate passed against the isolated fixture; the Code Review CLI "
        "completed all seven lenses with codex-cli/gpt-5.4. Apply these grounded checks while analyzing ambiguities."
    )
    evidence["context_sha256"] = _sha256(context)
    return evidence, context


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--preflight", type=Path, required=True)
    parser.add_argument("--tasks-root", type=Path, required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--task", type=Path, required=True)
    parser.add_argument("--agentskit", choices=("off", "on"), default="off")
    parser.add_argument("--agentskit-native-root", type=Path)
    parser.add_argument("--confirm", action="store_true")
    args = parser.parse_args()
    if not args.confirm:
        print(json.dumps({"status": "blocked", "reason": "explicit confirmation required"}))
        return 2

    manifest_path = args.run_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    expected = {
        "gate_mode": "technical-pilot",
        "analysis_eligible": False,
        "condition_id": f"compozy__reference__{args.agentskit}",
        "terminal_state": "NOT_APPLICABLE",
    }
    if any(manifest.get(key) != value for key, value in expected.items()):
        raise RuntimeError("Run bundle is not the prepared preregistered Compozy technical pilot")
    ledger_path = args.run_dir / "ledger.jsonl"
    if ledger_path.read_text(encoding="utf-8"):
        raise RuntimeError("Technical pilot ledger must be empty before execution")

    preflight = json.loads(args.preflight.read_text(encoding="utf-8"))
    condition = ConditionedPilotExecutor(preflight, gate_mode="technical-pilot").prepare_condition(
        run_id=str(manifest["run_id"]),
        ade="compozy",
        harness="reference",
        agentskit=args.agentskit,
    )
    ledger = Ledger(ledger_path, run_id=str(manifest["run_id"]), task_id=str(manifest["task_id"]))
    bundle = PreparedRunBundle(args.run_dir, manifest, ledger, condition)
    writer = RunBundleWriter(preflight, args.run_dir.parent, args.tasks_root, gate_mode="technical-pilot")
    ledger.record(
        stage_id="intake",
        actor="controller",
        event_type="run.started",
        time_category="orchestration_overhead",
        duration_ms=0,
        status="started",
        payload={"gate_mode": "technical-pilot", "analysis_eligible": False},
        tool="benchmark-controller",
    )

    task_text = args.task.read_text(encoding="utf-8")
    agentskit_context = ""
    prompt = ""
    attestation: dict[str, Any] = {
        "schema_version": "compozy-technical-pilot-v1.0",
        "run_id": manifest["run_id"],
        "condition_id": manifest["condition_id"],
        "provider": "codex",
        "model": "gpt-5.4",
        "prompt_sha256": None,
        "content_persisted": None,
        "analysis_eligible": False,
        "agentskit": {
            "enabled": args.agentskit == "on",
            "public_only": True,
            "agentskit_os_used": False,
            "context_sha256": None,
            "component_action_records": 0,
            "native_external_components_executed": False,
        },
        "commands": {},
        "cleanup": {},
    }
    session_id: str | None = None
    workspace_id: str | None = None
    technical_acceptance = False
    technical_pass = False
    failure: dict[str, Any] | None = None
    if args.agentskit == "on" and args.agentskit_native_root is None:
        raise RuntimeError("AgentsKit ON requires --agentskit-native-root")
    with tempfile.TemporaryDirectory(prefix="agentic-sdlc-compozy-technical-") as directory:
        fixture = Path(directory) / "greenfield"
        shutil.copytree(
            args.source,
            fixture,
            ignore=shutil.ignore_patterns("node_modules", ".next", ".git", ".DS_Store"),
        )
        before_sha256 = _tree_sha256(fixture)
        try:
            if args.agentskit == "on":
                action_bridge = AgentsKitComponentActionBridge(AgentsKitLedgerBridge(ledger, enabled=True))
                native_evidence, agentskit_context = _run_native_agentskit(
                    args.agentskit_native_root.resolve(), fixture, action_bridge,
                )
                attestation["agentskit"].update(native_evidence)
            prompt = (
                "Technical pipeline validation only. Do not edit, create, or delete files and do not run tools. "
                "Read the public task below, identify ambiguity IDs A1, A2, and A3, and end with the exact token "
                "TECHNICAL_PILOT_READY.\n\n" + task_text + agentskit_context
            )
            attestation["prompt_sha256"] = _sha256(prompt)
            code, output, duration = _run(
                "compozy", "session", "new", "--cwd", str(fixture), "--agent", "general", "--network", "local", "--json"
            )
            attestation["commands"]["session_new"] = {
                "returncode": code,
                "output_sha256": _sha256(output),
            }
            ledger.record(
                stage_id="requirements",
                actor="infrastructure",
                event_type="session.created",
                time_category="orchestration_overhead",
                duration_ms=duration,
                status="completed" if code == 0 else "failed",
                payload={"provider": "codex", "model": "gpt-5.4"},
                tool="compozy",
            )
            record = _session_record(output)
            session_id = str(record.get("id")) if record.get("id") else None
            workspace_id = str(record.get("workspace_id")) if record.get("workspace_id") else None
            if code != 0 or not session_id:
                raise RuntimeError("session_creation_failed")
            attestation["session_id_sha256"] = _sha256(session_id)
            if workspace_id:
                attestation["workspace_id_sha256"] = _sha256(workspace_id)

            code, output, duration = _run(
                "compozy", "session", "prompt", session_id, prompt,
                "--provider", "codex", "--model", "gpt-5.4", "--reasoning-effort", "low", "--json",
            )
            attestation["commands"]["session_prompt"] = {
                "returncode": code,
                "output_sha256": _sha256(output),
            }
            ledger.record(
                stage_id="requirements",
                actor="planner",
                event_type="model.prompt",
                time_category="effective_work",
                duration_ms=duration,
                status="completed" if code == 0 else "failed",
                payload={"provider": "codex", "model": "gpt-5.4", "prompt_sha256": _sha256(prompt)},
                tool="compozy",
            )
            if code != 0:
                raise RuntimeError("model_prompt_failed")

            code, events_output, duration = _run("compozy", "session", "events", session_id, "--last", "200", "--json")
            events = _events(events_output)
            event_types = Counter(str(event.get("type", "unknown")) for event in events)
            attestation["commands"]["session_events"] = {
                "returncode": code,
                "output_sha256": _sha256(events_output),
            }
            attestation["event_count"] = len(events)
            attestation["event_types"] = dict(sorted(event_types.items()))
            normalized = normalize_compozy_events(events)
            bridge = LifecycleBridge(ledger, tool="compozy")
            for event in normalized:
                bridge.record_external(event, stage_id="requirements", actor="infrastructure")
            attestation["normalized_lifecycle_count"] = len(normalized)
            sentinel_observed = "TECHNICAL_PILOT_READY" in events_output or "TECHNICAL_PILOT_READY" in output
            fixture_unchanged = _tree_sha256(fixture) == before_sha256
            attestation["sentinel_observed"] = sentinel_observed
            attestation["fixture_unchanged"] = fixture_unchanged
            technical_acceptance = code == 0 and bool(events) and bool(normalized) and sentinel_observed and fixture_unchanged
            if not technical_acceptance:
                raise RuntimeError("technical_acceptance_failed")
        except (RuntimeError, subprocess.TimeoutExpired, ValueError) as exc:
            failure = {"error_type": type(exc).__name__, "reason": str(exc)}
        finally:
            if session_id:
                code, output, _ = _run("compozy", "session", "stop", session_id, "--json")
                attestation["cleanup"]["session_stop"] = {"returncode": code, "output_sha256": _sha256(output)}
            if workspace_id:
                code, output, _ = _run("compozy", "workspace", "remove", workspace_id, "--json")
                attestation["cleanup"]["workspace_remove"] = {"returncode": code, "output_sha256": _sha256(output)}
            elif session_id:
                code, output, _ = _run("compozy", "session", "remove", session_id, "--json")
                attestation["cleanup"]["session_remove"] = {"returncode": code, "output_sha256": _sha256(output)}
    attestation["cleanup"]["fixture_destroyed"] = True
    session_residual = True
    workspace_residual = True
    for _ in range(10):
        _, sessions_output, _ = _run("compozy", "session", "list", "--json")
        sessions_payload = _json(sessions_output)
        sessions = sessions_payload.get("sessions", []) if isinstance(sessions_payload, dict) else []
        session_residual = any(
            isinstance(item, dict) and item.get("id") == session_id
            for item in sessions
        )
        _, workspaces_output, _ = _run("compozy", "workspace", "list", "--json")
        workspaces_payload = _json(workspaces_output)
        workspaces = workspaces_payload if isinstance(workspaces_payload, list) else []
        workspace_residual = any(
            isinstance(item, dict) and item.get("id") == workspace_id
            for item in workspaces
        )
        if not session_residual and not workspace_residual:
            break
        time.sleep(0.5)
    cleanup_verified = bool(session_id) and not session_residual and not workspace_residual
    attestation["cleanup"]["session_residual"] = session_residual
    attestation["cleanup"]["workspace_residual"] = workspace_residual
    attestation["cleanup"]["verified"] = cleanup_verified
    attestation["content_persisted"] = not cleanup_verified

    technical_pass = technical_acceptance and bool(attestation["cleanup"].get("verified"))
    if technical_acceptance and not technical_pass and failure is None:
        failure = {"error_type": "RuntimeError", "reason": "cleanup_verification_failed"}

    attestation["status"] = "technical-pass" if technical_pass else "technical-fail"
    if failure:
        attestation["failure"] = failure
    artifact_path = args.run_dir / "technical-pilot-attestation.json"
    _write_json(artifact_path, attestation)
    artifact = {
        "path": artifact_path.name,
        "sha256": _sha256(artifact_path.read_bytes()),
        "visibility": "public",
    }
    writer.finalize(
        bundle,
        terminal_state="TECHNICAL_PASS" if technical_pass else "TECHNICAL_FAIL",
        artifacts=[artifact],
        failure=failure,
    )
    print(json.dumps({"status": attestation["status"], "run_id": manifest["run_id"], "artifact_sha256": artifact["sha256"]}, sort_keys=True))
    return 0 if technical_pass else 1


if __name__ == "__main__":
    raise SystemExit(main())
