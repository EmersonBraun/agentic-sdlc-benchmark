#!/usr/bin/env python3
"""Run a bounded Compozy to Grok CLI ACP probe with redacted evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import secrets
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "controller/src"))

from benchmark_controller.compozy_grok import (  # noqa: E402
    MODEL_ID,
    PROVIDER_ID,
    REASONING_EFFORT,
    sha256_bytes,
    summarize_events,
    validate_provider_config,
)

PROBE_VERSION = "v1.2"
IGNORED_TREE_PARTS = {".git", ".compozy", ".next", "node_modules", "__pycache__"}


def tree_sha256(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        if any(part in IGNORED_TREE_PARTS for part in relative.parts):
            continue
        digest.update(relative.as_posix().encode())
        if path.is_symlink():
            digest.update(b"symlink\0" + str(path.readlink()).encode())
        elif path.is_file():
            digest.update(b"file\0" + path.read_bytes())
        else:
            digest.update(b"dir\0")
    return digest.hexdigest()


def matching_grok_pids() -> set[str]:
    completed = subprocess.run(
        ("pgrep", "-f", "grok agent .*stdio"), capture_output=True, text=True, check=False,
    )
    if completed.returncode not in {0, 1}:
        raise RuntimeError("could not inspect Grok ACP processes")
    return {line.strip() for line in completed.stdout.splitlines() if line.strip()}


def run_json(*command: str, timeout: int = 120) -> tuple[Any, dict[str, Any]]:
    started = time.monotonic_ns()
    completed = subprocess.run(command, capture_output=True, text=True, check=False, timeout=timeout)
    output = completed.stdout + completed.stderr
    evidence = {
        "argv_sha256": hashlib.sha256(json.dumps(command, separators=(",", ":")).encode()).hexdigest(),
        "output_sha256": hashlib.sha256(output.encode()).hexdigest(),
        "duration_ms": round((time.monotonic_ns() - started) / 1_000_000, 3),
        "returncode": completed.returncode,
    }
    if completed.returncode:
        raise RuntimeError(f"command failed: {Path(command[0]).name} {command[1] if len(command) > 1 else ''}")
    return json.loads(completed.stdout), evidence


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--attestation", type=Path, required=True)
    parser.add_argument("--confirm", action="store_true")
    args = parser.parse_args()
    if not args.confirm:
        print(json.dumps({"status": "blocked", "reason": "explicit confirmation required"}))
        return 2
    if args.attestation.exists():
        raise FileExistsError("attestation path must be new")

    commands: dict[str, Any] = {}
    config, commands["config_show"] = run_json("compozy", "config", "show", "-o", "json")
    provider = config.get("config", {}).get("providers", {}).get(PROVIDER_ID)
    if not isinstance(provider, dict):
        raise RuntimeError("grok-cli provider is absent from effective Compozy config")
    argv = validate_provider_config(provider)

    executable = Path(argv[0]).expanduser()
    if not executable.is_absolute():
        resolved = shutil.which(str(executable))
        if not resolved:
            raise RuntimeError("Grok CLI executable cannot be resolved")
        executable = Path(resolved)
    executable = executable.resolve()
    if not executable.is_file():
        raise RuntimeError("resolved Grok CLI executable is not a file")

    version_result = subprocess.run((str(executable), "version"), capture_output=True, text=True, check=False, timeout=30)
    version_output = version_result.stdout + version_result.stderr
    commands["grok_version"] = {
        "output_sha256": hashlib.sha256(version_output.encode()).hexdigest(),
        "returncode": version_result.returncode,
    }
    if version_result.returncode or "grok " not in version_output.lower():
        raise RuntimeError("Grok CLI version probe failed")

    sentinel = "GROK_COMPOZY_" + secrets.token_hex(12).upper()
    workspace_before = tree_sha256(ROOT)
    grok_pids_before = matching_grok_pids()
    session_id: str | None = None
    summary: dict[str, Any] = {}
    cleanup = {"stop_returncode": None, "active_session_residual": True}
    failure: str | None = None
    try:
        created, commands["session_new"] = run_json(
            "compozy", "session", "new", "--cwd", str(ROOT), "--agent", "general",
            "--network", "local", "-o", "json",
        )
        session_id = str(created.get("id", ""))
        if not session_id:
            raise RuntimeError("Compozy returned no session id")
        prompt_events, commands["session_prompt"] = run_json(
            "compozy", "session", "prompt", session_id,
            f"Reply exactly {sentinel}. Do not call tools.", "--provider", PROVIDER_ID, "-o", "json",
            timeout=180,
        )
        if not isinstance(prompt_events, list):
            raise RuntimeError("Compozy prompt returned an invalid event stream")
        events, commands["session_events"] = run_json(
            "compozy", "session", "events", session_id, "--last", "200", "-o", "json",
        )
        if not isinstance(events, list):
            raise RuntimeError("Compozy session events returned an invalid stream")
        summary = summarize_events(events, sentinel)
        if not summary["sentinel_observed"] or not summary["done_observed"]:
            raise RuntimeError("Grok CLI sentinel or terminal event was not observed")
        if summary["providers"] != [PROVIDER_ID]:
            raise RuntimeError("Compozy event stream did not preserve the exact provider identity")
    except Exception as exc:
        failure = f"{type(exc).__name__}: {exc}"
    finally:
        if session_id:
            stopped = subprocess.run(
                ("compozy", "session", "stop", session_id, "-o", "json"),
                capture_output=True, text=True, check=False, timeout=30,
            )
            cleanup["stop_returncode"] = stopped.returncode
            commands["session_stop"] = {
                "output_sha256": hashlib.sha256((stopped.stdout + stopped.stderr).encode()).hexdigest(),
                "returncode": stopped.returncode,
            }
    sessions, commands["session_list"] = run_json("compozy", "session", "list", "-o", "json")
    active = sessions.get("sessions", []) if isinstance(sessions, dict) else []
    cleanup["active_session_residual"] = any(
        isinstance(item, dict) and item.get("id") == session_id for item in active
    )
    workspace_after = tree_sha256(ROOT)
    workspace_unchanged = workspace_before == workspace_after
    grok_pids_after = matching_grok_pids()
    cleanup["new_grok_process_residual_count"] = len(grok_pids_after - grok_pids_before)
    passed = (
        failure is None
        and cleanup["stop_returncode"] == 0
        and not cleanup["active_session_residual"]
        and cleanup["new_grok_process_residual_count"] == 0
        and workspace_unchanged
    )

    document = {
        "schema_version": "compozy-grok-cli-readiness-v1.2",
        "probe_version": PROBE_VERSION,
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "status": "passed" if passed else "failed",
        "analysis_eligible": False,
        "provider": {
            "id": PROVIDER_ID,
            "auth_mode": "native_cli",
            "compozy_bound_credential_slots": 0,
            "api_credential_absence_observed": False,
            "transport": "acp-stdio",
            "configured_model_argument": MODEL_ID,
            "configured_reasoning_argument": REASONING_EFFORT,
            "runtime_reported_model_observed": False,
            "command_sha256": hashlib.sha256("\0".join(argv).encode()).hexdigest(),
            "executable_sha256": sha256_bytes(executable.read_bytes()),
            "executable_basename": executable.name,
            "version": version_output.strip(),
            "version_output_sha256": hashlib.sha256(version_output.encode()).hexdigest(),
        },
        "execution": summary,
        "workspace": {
            "unchanged": workspace_unchanged,
            "before_sha256": workspace_before,
            "after_sha256": workspace_after,
            "ignored_parts": sorted(IGNORED_TREE_PARTS),
        },
        "cleanup": cleanup,
        "commands": commands,
        "redaction": {
            "public_attestation_contains_raw_prompt": False,
            "public_attestation_contains_raw_model_output": False,
            "local_stopped_session_history_retained": True,
            "session_id_sha256": hashlib.sha256((session_id or "").encode()).hexdigest(),
            "sentinel_sha256": hashlib.sha256(sentinel.encode()).hexdigest(),
        },
        "limitations": [
            "Grok ACP does not advertise a mutable model option; model and reasoning are pinned as process arguments.",
            "The probe verifies that Compozy binds no credential slots, not the complete child-process environment.",
            "Stopped Compozy session history is retained locally and excluded from the public attestation.",
        ],
        "source_hashes": {
            "controller/scripts/probe_compozy_grok_cli.py": sha256_bytes(Path(__file__).read_bytes()),
            "controller/src/benchmark_controller/compozy_grok.py": sha256_bytes(
                (ROOT / "controller/src/benchmark_controller/compozy_grok.py").read_bytes()
            ),
            "adapters/compozy-grok-cli-provider-v1.2.toml": sha256_bytes(
                (ROOT / "adapters/compozy-grok-cli-provider-v1.2.toml").read_bytes()
            ),
        },
    }
    if failure:
        document["failure"] = failure
    args.attestation.parent.mkdir(parents=True, exist_ok=True)
    args.attestation.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": document["status"], "attestation": str(args.attestation)}))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
