#!/usr/bin/env python3
"""Probe Agent Orchestrator's native Grok 4.5 worker path with redacted evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import plistlib
import re
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

AO = Path("/Applications/Agent Orchestrator.app/Contents/Resources/daemon/ao")
AO_PLIST = Path("/Applications/Agent Orchestrator.app/Contents/Info.plist")
GROK = Path.home() / ".grok/bin/grok"
SESSION_PATTERN = re.compile(r"spawned session ([A-Za-z0-9_-]+)")
SENTINEL = "V12_AO_GROK45_READY"


def _run(*args: str, timeout: int = 30) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, text=True, capture_output=True, check=False, timeout=timeout)


def _sha(value: bytes | str) -> str:
    if isinstance(value, str):
        value = value.encode()
    return hashlib.sha256(value).hexdigest()


def _record(result: subprocess.CompletedProcess[str]) -> dict[str, Any]:
    return {"returncode": result.returncode, "output_sha256": _sha(result.stdout + result.stderr)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", default="code-10x")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--confirm", action="store_true")
    args = parser.parse_args()
    if not args.confirm:
        print(json.dumps({"status": "blocked", "reason": "confirmation-required"}))
        return 2

    result: dict[str, Any] = {
        "schema_version": "ao-grok-v1.2-readiness-attestation",
        "protocol_version": "v1.2",
        "analysis_eligible": False,
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "ade": "agent-orchestrator",
        "role": "executor_fixer",
        "provider": "grok-cli",
        "configured_model": "grok-4.5",
        "transport": "ao-native-tui-session",
        "raw_content_persisted": False,
        "commands": {},
        "cleanup": {},
        "source_hashes": {
            "probe": _sha(Path(__file__).read_bytes()),
            "ao_executable": _sha(AO.read_bytes()),
            "grok_executable": _sha(GROK.read_bytes()),
        },
    }
    session_id: str | None = None
    try:
        project = _run(str(AO), "project", "get", args.project, "--json")
        result["commands"]["project_get"] = _record(project)
        payload = json.loads(project.stdout)
        config = payload["project"]["config"]
        result["project_config_sha256"] = _sha(json.dumps(config, sort_keys=True, separators=(",", ":")))
        worker = config.get("worker", {})
        orchestrator = config.get("orchestrator", {})
        result["role_topology_configured"] = (
            worker.get("agent") == "grok"
            and worker.get("agentConfig", {}).get("model") == "grok-4.5"
            and orchestrator.get("agent") == "codex"
            and orchestrator.get("agentConfig", {}).get("model") == "gpt-5.4"
        )
        if project.returncode or not result["role_topology_configured"]:
            raise RuntimeError("AO project role topology is not pinned")

        prompt = f"Read-only protocol probe. Do not edit files or run tools. Reply with exactly {SENTINEL}."
        spawn = _run(
            str(AO), "spawn", "--project", args.project, "--name", "v12-grok45-probe",
            "--issue", "18", "--prompt", prompt, "--kind", "worker", "--mode", "tui",
            timeout=60,
        )
        result["commands"]["spawn"] = _record(spawn)
        match = SESSION_PATTERN.search(spawn.stdout + spawn.stderr)
        session_id = match.group(1) if match else None
        if spawn.returncode or not session_id:
            raise RuntimeError("AO did not create the Grok worker session")
        result["session_id_sha256"] = _sha(session_id)

        capture = ""
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            observed = _run("tmux", "capture-pane", "-pt", session_id, "-S", "-240")
            capture = observed.stdout + observed.stderr
            if SENTINEL in capture and "Grok 4.5" in capture:
                break
            time.sleep(1)
        result["capture_sha256"] = _sha(capture)
        result["sentinel_observed"] = SENTINEL in capture
        result["effective_model_observed"] = "Grok 4.5" in capture
        result["trust_prompt_observed"] = "Do you trust the contents" in capture

        session = _run(str(AO), "session", "get", session_id, "--project", args.project, "--json")
        result["commands"]["session_get"] = _record(session)
        session_payload = json.loads(session.stdout).get("session", {})
        workspace = Path(str(session_payload.get("workspacePath") or session_payload.get("workspace_path") or ""))
        if not workspace.is_dir():
            workspace = Path.home() / ".ao/data/worktrees" / args.project / session_id
        status = _run("git", "-C", str(workspace), "status", "--porcelain", "--untracked-files=all")
        changed_paths = sorted(line[3:] for line in status.stdout.splitlines() if len(line) > 3)
        result["workspace"] = {
            "path_sha256": _sha(str(workspace.resolve())),
            "clean": status.returncode == 0 and status.stdout == "",
            "status_sha256": _sha(status.stdout + status.stderr),
            "changed_paths": changed_paths,
        }
        result["status"] = "passed" if all((
            result["sentinel_observed"], result["effective_model_observed"],
            not result["trust_prompt_observed"], result["workspace"]["clean"],
        )) else "failed"
    except Exception as exc:
        result["status"] = "failed"
        result["failure"] = {"error_type": type(exc).__name__, "reason": str(exc)}
    finally:
        if session_id:
            killed = _run(str(AO), "session", "kill", session_id, "--project", args.project)
            result["cleanup"]["kill"] = _record(killed)
            cleaned = _run(str(AO), "session", "cleanup", "--project", args.project, "--yes", timeout=60)
            result["cleanup"]["reclaim"] = _record(cleaned)
            listed = _run(str(AO), "session", "ls", "--all", "--project", args.project, "--json")
            result["cleanup"]["session_residual"] = session_id in listed.stdout
            result["cleanup"]["verified"] = (
                killed.returncode == 0 and cleaned.returncode == 0 and session_id not in listed.stdout
            )
        else:
            result["cleanup"]["verified"] = True
    if not result["cleanup"]["verified"]:
        result["status"] = "failed"
    with AO_PLIST.open("rb") as stream:
        result["versions"] = {
            "agent_orchestrator": str(plistlib.load(stream)["CFBundleShortVersionString"]),
            "grok": _run(str(GROK), "--version").stdout.strip(),
        }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": result["status"], "output": str(args.output), "sha256": _sha(args.output.read_bytes())}))
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
