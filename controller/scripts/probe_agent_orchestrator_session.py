#!/usr/bin/env python3
"""Run the explicitly-confirmed AO session parity probe in a disposable fixture."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from benchmark_controller.ledger import Ledger

CLI = "/Applications/Agent Orchestrator.app/Contents/Resources/daemon/ao"


def _run(*args: str) -> tuple[int, str]:
    completed = subprocess.run((CLI, *args), capture_output=True, text=True, check=False)
    return completed.returncode, completed.stdout + completed.stderr


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _json(value: str) -> object:
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return None


def _session_items(value: str) -> list[dict[str, object]]:
    payload = _json(value)
    if not isinstance(payload, dict):
        return []
    for key in ("data", "sessions"):
        items = payload.get(key)
        if isinstance(items, list):
            return [item for item in items if isinstance(item, dict)]
    return []


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--confirm",
        action="store_true",
        help="Confirm creation of one temporary AO session; without this flag nothing executes.",
    )
    args = parser.parse_args()
    if not args.confirm:
        print(json.dumps({"executable": False, "reason": "operator confirmation required"}, indent=2))
        return 2

    source = Path("products/greenfield").resolve()
    project_id = "benchmark-session-parity-ao"
    with tempfile.TemporaryDirectory(prefix="agentic-sdlc-ao-parity-") as directory:
        root = Path(directory)
        fixture = root / "greenfield"
        remote = root / "greenfield-origin.git"
        shutil.copytree(source, fixture, ignore=shutil.ignore_patterns("node_modules", ".next", ".git", ".DS_Store"))
        for command in (
            ("git", "init", "-q"),
            ("git", "branch", "-M", "main"),
            ("git", "config", "user.email", "benchmark@example.invalid"),
            ("git", "config", "user.name", "Benchmark Probe"),
            ("git", "add", "."),
            ("git", "commit", "-qm", "fixture snapshot"),
        ):
            subprocess.run(command, cwd=fixture, check=True)
        subprocess.run(("git", "init", "--bare", "-q", str(remote)), cwd=root, check=True)
        subprocess.run(("git", "remote", "add", "origin", str(remote)), cwd=fixture, check=True)
        subprocess.run(("git", "push", "-q", "-u", "origin", "main"), cwd=fixture, check=True)
        subprocess.run(("git", "remote", "set-head", "origin", "main"), cwd=fixture, check=True)

        ledger_path = root / "ledger.jsonl"
        ledger = Ledger(ledger_path, run_id="run_session-parity-ao", task_id="pilot_session-parity")
        result: dict[str, object] = {
            "schema_version": "agent-orchestrator-session-attestation-v1.0",
            "agent_sessions_started": False,
            "fixture_mutated": False,
            "commands": {},
            "session": {},
            "cleanup": {},
        }
        session_id: str | None = None
        try:
            code, output = _run("project", "add", "--id", project_id, "--name", "parity-probe", "--path", str(fixture), "--worker-agent", "codex", "--orchestrator-agent", "codex")
            result["commands"]["project_add"] = {"returncode": code, "output_sha256": _hash(output)}
            if code != 0:
                raise RuntimeError("project registration failed")
            prompt = "Session parity probe only. Do not edit, create, delete, install, or commit files. Reply exactly PARITY_PROBE_READY and wait."
            code, output = _run("spawn", "--project", project_id, "--name", "parity-probe", "--harness", "codex", "--kind", "worker", "--mode", "chat", "--issue", "session-parity", "--prompt", prompt)
            result["commands"]["spawn"] = {"returncode": code, "output_sha256": _hash(output)}
            if code != 0:
                raise RuntimeError("session spawn failed")
            result["agent_sessions_started"] = True
            ledger.record(stage_id="intake", actor="infrastructure", event_type="lifecycle.session.created", time_category="orchestration_overhead", duration_ms=0, status="completed", payload={"spawn_output_sha256": _hash(output)}, tool="agent-orchestrator")
            observed: list[dict[str, object]] = []
            for _ in range(15):
                code, output = _run("session", "ls", "--all", "--project", project_id, "--json")
                observed = _session_items(output)
                if observed:
                    break
                time.sleep(1)
            result["session"]["observed_count"] = len(observed)
            session_id = next((str(item.get("id")) for item in observed if item.get("id")), None)
            if not session_id:
                raise RuntimeError("session id was not exposed by read-only listing")
            result["session"]["session_id_sha256"] = _hash(session_id)
            code, output = _run("session", "kill", session_id, "-p", project_id)
            result["commands"]["kill"] = {"returncode": code, "output_sha256": _hash(output)}
            ledger.record(stage_id="intake", actor="infrastructure", event_type="lifecycle.session.terminated", time_category="orchestration_overhead", duration_ms=0, status="completed" if code == 0 else "failed", payload={"session_id_sha256": _hash(session_id)}, tool="agent-orchestrator")
            if code != 0:
                raise RuntimeError("session termination failed")
        except Exception as exc:
            result["error_type"] = type(exc).__name__
            result["error"] = str(exc)
        finally:
            code, output = _run("project", "rm", project_id, "-y", "--json")
            result["cleanup"]["project_remove"] = {"returncode": code, "output_sha256": _hash(output)}
            result["cleanup"]["fixture_destroyed"] = True
            result["ledger_event_count"] = sum(1 for _ in ledger_path.open(encoding="utf-8")) if ledger_path.exists() else 0
        print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result.get("error_type") is None else 1


if __name__ == "__main__":
    raise SystemExit(main())
