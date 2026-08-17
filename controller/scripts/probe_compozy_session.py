#!/usr/bin/env python3
"""Run the explicitly-confirmed Compozy session probe in a disposable fixture."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

CLI = os.environ.get("COMPOZY_CLI", "compozy")


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


def _sessions(value: str) -> list[dict[str, object]]:
    payload = _json(value)
    if isinstance(payload, list):
        return [record for record in payload if isinstance(record, dict)]
    if not isinstance(payload, dict):
        return []
    if payload.get("id"):
        return [payload]
    records = payload.get("sessions", payload.get("data", []))
    return [record for record in records if isinstance(record, dict)] if isinstance(records, list) else []


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--confirm", action="store_true", help="Confirm one temporary Compozy session")
    args = parser.parse_args()
    if not args.confirm:
        print(json.dumps({"executable": False, "reason": "operator confirmation required"}, indent=2))
        return 2

    source = Path("products/greenfield").resolve()
    with tempfile.TemporaryDirectory(prefix="agentic-sdlc-compozy-parity-") as directory:
        fixture = Path(directory) / "greenfield"
        shutil.copytree(source, fixture, ignore=shutil.ignore_patterns("node_modules", ".next", ".git", ".DS_Store"))
        result: dict[str, object] = {
            "schema_version": "compozy-session-attestation-v1.0",
            "fixture_mutated": False,
            "session_created": False,
            "provider_execution_observed": False,
            "commands": {},
            "cleanup": {},
        }
        session_id: str | None = None
        workspace_id: str | None = None
        stopped = False
        workspace_removed = False
        try:
            code, output = _run("session", "new", "--cwd", str(fixture), "--agent", "general", "--network", "local", "--json")
            result["commands"]["session_new"] = {"returncode": code, "output_sha256": _hash(output)}
            records = _sessions(output)
            if code != 0 or not records:
                raise RuntimeError("Compozy session creation did not return a session record")
            record = records[0]
            session_id = str(record.get("id")) if record.get("id") else None
            workspace_id = str(record.get("workspace_id")) if record.get("workspace_id") else None
            if not session_id:
                raise RuntimeError("Compozy session id was not exposed")
            result["session_created"] = True
            result["session_id_sha256"] = _hash(session_id)
            result["initial_state"] = record.get("state")
            result["runtime_status"] = record.get("runtime", {}).get("status") if isinstance(record.get("runtime"), dict) else None
            result["network_mode"] = record.get("resolved_network_participation", {}).get("mode") if isinstance(record.get("resolved_network_participation"), dict) else None
            if workspace_id:
                result["workspace_id_sha256"] = _hash(workspace_id)
            code, output = _run("session", "stop", session_id, "--json")
            result["commands"]["session_stop"] = {"returncode": code, "output_sha256": _hash(output)}
            if code != 0:
                raise RuntimeError("Compozy session stop failed")
            stopped = True
            if workspace_id:
                code, output = _run("workspace", "remove", workspace_id, "--json")
                result["cleanup"]["workspace_remove"] = {"returncode": code, "output_sha256": _hash(output)}
                if code != 0:
                    raise RuntimeError("Compozy workspace removal failed")
                workspace_removed = True
        except Exception as exc:
            result["error_type"] = type(exc).__name__
            result["error"] = str(exc)
        finally:
            if session_id and not stopped:
                code, output = _run("session", "stop", session_id, "--json")
                result["cleanup"]["emergency_session_stop"] = {"returncode": code, "output_sha256": _hash(output)}
                stopped = code == 0
            if workspace_id and stopped and not workspace_removed:
                code, output = _run("workspace", "remove", workspace_id, "--json")
                result["cleanup"]["emergency_workspace_remove"] = {"returncode": code, "output_sha256": _hash(output)}
            result["cleanup"]["fixture_destroyed"] = True
        print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result.get("error_type") is None else 1


if __name__ == "__main__":
    raise SystemExit(main())
