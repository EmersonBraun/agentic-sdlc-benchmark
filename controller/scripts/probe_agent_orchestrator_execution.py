#!/usr/bin/env python3
"""Run one bounded, disposable AO gpt-5.4 execution and emit redacted evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from benchmark_controller.ao_evidence import (
    evidence_passes,
    read_codex_execution_identity,
    read_provider_evidence,
    read_session_metadata,
    sha256_text,
)
from benchmark_controller.ao_lifecycle import SessionLifecycleObserver
from benchmark_controller.external import LifecycleBridge
from benchmark_controller.ledger import Ledger

CLI = "/Applications/Agent Orchestrator.app/Contents/Resources/daemon/ao"
DATABASE = Path.home() / ".ao" / "data" / "ao.db"
MODEL = "gpt-5.4"
EXPECTED_REPLY = "PARITY_PROBE_READY"
AO_VERSION = "0.12.6"
PROBE_COMMAND = [
    "PYTHONPATH=controller/src",
    "python3",
    "controller/scripts/probe_agent_orchestrator_execution.py",
    "--confirm",
]


def _run(*args: str) -> tuple[int, str]:
    completed = subprocess.run((CLI, *args), capture_output=True, text=True, check=False)
    return completed.returncode, completed.stdout + completed.stderr


def _json(output: str) -> dict[str, Any]:
    try:
        value = json.loads(output)
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def _sessions(output: str) -> list[dict[str, Any]]:
    value = _json(output).get("data")
    if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
        raise ValueError("AO session listing returned an invalid schema")
    return value


def _command_record(code: int, output: str) -> dict[str, Any]:
    return {"returncode": code, "output_sha256": sha256_text(output)}


def _tree_sha256(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        if relative.parts and relative.parts[0] == ".git":
            continue
        digest.update(str(relative).encode("utf-8"))
        if path.is_symlink():
            digest.update(b"symlink\0" + str(path.readlink()).encode("utf-8"))
        elif path.is_file():
            digest.update(b"file\0" + path.read_bytes())
        elif path.is_dir():
            digest.update(b"dir\0")
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--confirm", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if not args.confirm:
        print(json.dumps({"executable": False, "reason": "operator confirmation required"}, indent=2))
        return 2

    project_id = f"benchmark-ao-execution-{int(time.time())}"
    result: dict[str, Any] = {
        "schema_version": "agent-orchestrator-execution-attestation-v1.1",
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "analysis_eligible": False,
        "operator": "local-primary-operator",
        "component_version": AO_VERSION,
        "runtime_sha256": hashlib.sha256(Path(CLI).read_bytes()).hexdigest(),
        "probe_command": PROBE_COMMAND,
        "public_cli_event_stream": "not-exposed",
        "datastore_access": "read-only-redacted",
        "configured_model": MODEL,
        "probe_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "commands": {},
        "session": {},
        "cleanup": {},
    }
    session_id: str | None = None
    terminated = False
    with tempfile.TemporaryDirectory(prefix="agentic-sdlc-ao-execution-") as directory:
        root = Path(directory)
        fixture = root / "fixture"
        remote = root / "origin.git"
        shutil.copytree(Path("products/greenfield").resolve(), fixture, ignore=shutil.ignore_patterns("node_modules", ".next", ".git", ".DS_Store"))
        for command in (
            ("git", "init", "-q"), ("git", "branch", "-M", "main"),
            ("git", "config", "user.email", "benchmark@example.invalid"),
            ("git", "config", "user.name", "Benchmark Probe"), ("git", "add", "."),
            ("git", "commit", "-qm", "fixture snapshot"),
        ):
            subprocess.run(command, cwd=fixture, check=True)
        subprocess.run(("git", "init", "--bare", "-q", str(remote)), cwd=root, check=True)
        subprocess.run(("git", "remote", "add", "origin", str(remote)), cwd=fixture, check=True)
        subprocess.run(("git", "push", "-q", "-u", "origin", "main"), cwd=fixture, check=True)
        subprocess.run(("git", "symbolic-ref", "HEAD", "refs/heads/main"), cwd=remote, check=True)
        subprocess.run(("git", "remote", "set-head", "origin", "main"), cwd=fixture, check=True)
        fixture_commit = subprocess.run(
            ("git", "rev-parse", "HEAD"), cwd=fixture, check=True, capture_output=True, text=True
        ).stdout.strip()
        result["workspace_commit_sha256"] = sha256_text(fixture_commit)
        fixture_tree_sha256 = _tree_sha256(fixture)
        result["fixture_tree_sha256"] = fixture_tree_sha256

        ledger_path = root / "ledger.jsonl"
        observer = SessionLifecycleObserver(LifecycleBridge(Ledger(ledger_path, run_id="run_ao_execution_probe", task_id="pilot_session_parity"), tool="agent-orchestrator"))
        try:
            code, output = _run("project", "add", "--id", project_id, "--name", "ao-execution-probe", "--path", str(fixture), "--worker-agent", "codex", "--orchestrator-agent", "codex")
            result["commands"]["project_add"] = _command_record(code, output)
            if code:
                raise RuntimeError("project registration failed")
            config = {"agentConfig": {}, "worker": {"agent": "codex", "agentConfig": {"model": MODEL, "permissions": "default"}}, "orchestrator": {"agent": "codex", "agentConfig": {}}, "trackerIntake": {}}
            code, output = _run("project", "set-config", project_id, "--config-json", json.dumps(config, separators=(",", ":")), "--json")
            result["commands"]["project_config"] = _command_record(code, output)
            configured = _json(output).get("project", {}).get("config", {}).get("worker", {}).get("agentConfig", {}).get("model")
            result["model_configuration_observed"] = configured == MODEL
            result["permission_configuration_observed"] = (
                _json(output).get("project", {}).get("config", {}).get("worker", {}).get("agentConfig", {}).get("permissions") == "default"
            )
            if code or configured != MODEL or not result["permission_configuration_observed"]:
                raise RuntimeError("exact model configuration not observed")
            prompt = "Read-only parity probe. Do not change files or run tools. Reply exactly PARITY_PROBE_READY."
            code, output = _run("spawn", "--project", project_id, "--name", "ao-execution", "--harness", "codex", "--kind", "worker", "--mode", "chat", "--issue", "ao-parity", "--prompt", prompt)
            result["commands"]["spawn"] = _command_record(code, output)
            if code:
                raise RuntimeError("session spawn failed")
            deadline = time.monotonic() + 180
            evidence: dict[str, Any] = {}
            identity: dict[str, Any] = {}
            metadata: dict[str, Any] = {}
            while time.monotonic() < deadline:
                code, output = _run("session", "ls", "--all", "--project", project_id, "--json")
                items = _sessions(output)
                if items:
                    session_id = str(items[0].get("id", "")) or None
                    observer.observe(items[0])
                if session_id:
                    evidence = read_provider_evidence(DATABASE, session_id, EXPECTED_REPLY)
                    metadata = read_session_metadata(DATABASE, session_id)
                    if metadata.get("metadata_observed"):
                        identity = read_codex_execution_identity(
                            Path.home() / ".codex" / "sessions",
                            str(metadata["provider_conversation_id"]),
                        )
                    if evidence_passes(evidence, identity, MODEL):
                        break
                time.sleep(1)
            result["provider_evidence"] = evidence
            result["model_identity"] = identity
            result["datastore_schema_sha256"] = metadata.get("schema_sha256")
            result["session"]["session_id_sha256"] = sha256_text(session_id or "")
            result["session"]["model_execution_observed"] = evidence_passes(evidence, identity, MODEL)
            if not result["session"]["model_execution_observed"]:
                raise RuntimeError("bounded model execution evidence incomplete")
            workspace = Path(str(metadata["workspace_path"]))
            status = subprocess.run(
                ("git", "status", "--porcelain", "--untracked-files=all"),
                cwd=workspace, check=True, capture_output=True, text=True,
            ).stdout
            head = subprocess.run(
                ("git", "rev-parse", "HEAD"), cwd=workspace, check=True, capture_output=True, text=True,
            ).stdout.strip()
            result["workspace"] = {
                "path_sha256": sha256_text(str(workspace)),
                "head_matches_fixture": head == fixture_commit,
                "clean": status == "",
                "status_sha256": sha256_text(status),
                "complete_tree_matches_fixture": _tree_sha256(workspace) == fixture_tree_sha256,
            }
            if status or head != fixture_commit or not result["workspace"]["complete_tree_matches_fixture"]:
                raise RuntimeError("AO execution workspace was mutated")
            code, output = _run("session", "kill", session_id, "-p", project_id)
            result["commands"]["kill"] = _command_record(code, output)
            if code:
                raise RuntimeError("session termination failed")
            terminated = True
            observer.observe({"id": session_id, "status": "terminated"})
        except Exception as exc:
            result["error_type"] = type(exc).__name__
            result["error"] = str(exc)
        finally:
            if session_id and not terminated:
                code, output = _run("session", "kill", session_id, "-p", project_id)
                result["cleanup"]["emergency_kill"] = _command_record(code, output)
            code, output = _run("session", "ls", "--all", "--include-terminated", "--project", project_id, "--json")
            result["cleanup"]["session_list"] = _command_record(code, output)
            try:
                cleanup_sessions = _sessions(output)
            except ValueError:
                cleanup_sessions = []
                result["cleanup"]["session_schema_valid"] = False
                result["cleanup"]["active_session_leak_count"] = None
            else:
                result["cleanup"]["session_schema_valid"] = True
                result["cleanup"]["active_session_leak_count"] = sum(
                    not bool(item.get("isTerminated")) for item in cleanup_sessions
                )
                target_sessions = [item for item in cleanup_sessions if item.get("id") == session_id]
                result["cleanup"]["target_session_terminated"] = (
                    len(target_sessions) == 1 and bool(target_sessions[0].get("isTerminated"))
                )
            code, output = _run("project", "rm", project_id, "-y", "--json")
            result["cleanup"]["project_remove"] = _command_record(code, output)
            result["cleanup"]["fixture_destroyed"] = True
            result["ledger_event_count"] = sum(1 for _ in ledger_path.open(encoding="utf-8")) if ledger_path.exists() else 0

    cleanup_passed = (
        result["cleanup"].get("active_session_leak_count") == 0
        and result["cleanup"].get("session_schema_valid") is True
        and result["cleanup"].get("target_session_terminated") is True
        and result["cleanup"].get("session_list", {}).get("returncode") == 0
        and result["cleanup"].get("project_remove", {}).get("returncode") == 0
    )
    result["cleanup"]["passed"] = cleanup_passed
    result["status"] = "passed" if result.get("error_type") is None and cleanup_passed else "failed"
    rendered = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
