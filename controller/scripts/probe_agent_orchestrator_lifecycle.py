#!/usr/bin/env python3
"""Inspect Agent Orchestrator's read-only lifecycle surface without spawning."""

from __future__ import annotations

import hashlib
import json
import subprocess

CLI = "/Applications/Agent Orchestrator.app/Contents/Resources/daemon/ao"


def _run(*args: str) -> dict[str, object]:
    command = (CLI, *args)
    completed = subprocess.run(command, capture_output=True, text=True, check=False)
    output = completed.stdout + completed.stderr
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError:
        payload = None
    values = payload.get("data", payload.get("sessions", [])) if isinstance(payload, dict) else []
    return {
        "returncode": completed.returncode,
        "output_sha256": hashlib.sha256(output.encode("utf-8")).hexdigest(),
        "count": len(values) if isinstance(values, list) else None,
        "machine_readable": isinstance(payload, dict),
    }


def _help(*args: str) -> dict[str, object]:
    command = (CLI, *args, "--help")
    completed = subprocess.run(command, capture_output=True, text=True, check=False)
    output = completed.stdout + completed.stderr
    return {
        "returncode": completed.returncode,
        "output_sha256": hashlib.sha256(output.encode("utf-8")).hexdigest(),
        "event_command_exposed": "event" in output.lower(),
    }


def main() -> int:
    result = {
        "schema_version": "agent-orchestrator-lifecycle-attestation-v1.0",
        "side_effect_policy": {
            "agent_sessions_started": False,
            "orchestrator_sessions_started": False,
            "raw_payloads_published": False,
        },
        "read_only_commands": {
            "orchestrator_list": _run("orchestrator", "ls", "--json"),
            "session_list_all": _run("session", "ls", "--all", "--json"),
            "session_list_project": _run("session", "ls", "--project", "code-10x", "--json"),
        },
        "command_surface": {
            "orchestrator_help": _help("orchestrator"),
            "session_help": _help("session"),
        },
        "decision": "blocked: the CLI exposes session listing but no lifecycle event stream or subscription surface; live lifecycle parity cannot be verified without a declared session test.",
    }
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
