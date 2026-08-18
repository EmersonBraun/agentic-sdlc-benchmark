#!/usr/bin/env python3
"""Probe the fixed Codex-planner to Grok-executor topology in one Compozy session."""

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
    PROVIDER_ID as GROK_PROVIDER,
    sha256_bytes,
    validate_provider_config,
)

CODEX_PROVIDER = "codex"
CODEX_MODEL = "gpt-5.4"
GROK_MODEL = "grok-4.5"
IGNORED_TREE_PARTS = {".git", ".compozy", ".next", "node_modules", "__pycache__"}


def _sha(value: bytes | str) -> str:
    if isinstance(value, str):
        value = value.encode()
    return hashlib.sha256(value).hexdigest()


def _tree_sha(root: Path) -> str:
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


def _run_json(*command: str, timeout: int = 180) -> tuple[Any, dict[str, Any]]:
    started = time.monotonic_ns()
    completed = subprocess.run(command, capture_output=True, text=True, check=False, timeout=timeout)
    output = completed.stdout + completed.stderr
    record = {
        "argv_sha256": _sha(json.dumps(command, separators=(",", ":"))),
        "output_sha256": _sha(output),
        "returncode": completed.returncode,
        "duration_ms": round((time.monotonic_ns() - started) / 1_000_000, 3),
    }
    if completed.returncode:
        raise RuntimeError(f"command failed: {Path(command[0]).name} {command[1]}")
    return json.loads(completed.stdout), record


def _matching_grok_pids() -> set[str]:
    completed = subprocess.run(("pgrep", "-f", "grok agent .*stdio"), capture_output=True, text=True, check=False)
    if completed.returncode not in {0, 1}:
        raise RuntimeError("Grok ACP process inventory failed")
    return {line.strip() for line in completed.stdout.splitlines() if line.strip()}


def _summarize_turn(events: list[dict[str, Any]], sentinel: str) -> dict[str, Any]:
    event_types: dict[str, int] = {}
    text_parts: list[str] = []
    providers: set[str] = set()
    models: set[str] = set()
    reasoning_efforts: set[str] = set()
    for event in events:
        event_type = str(event.get("type", "unknown"))
        event_types[event_type] = event_types.get(event_type, 0) + 1
        if event_type == "agent_message":
            text = event.get("text")
            if isinstance(text, str):
                text_parts.append(text)
        runtime = event.get("prompt_runtime")
        if not isinstance(runtime, dict):
            content = event.get("content")
            runtime = content.get("prompt_runtime") if isinstance(content, dict) else None
        if isinstance(runtime, dict):
            if isinstance(runtime.get("provider"), str):
                providers.add(runtime["provider"])
            if isinstance(runtime.get("model"), str):
                models.add(runtime["model"])
            if isinstance(runtime.get("reasoning_effort"), str):
                reasoning_efforts.add(runtime["reasoning_effort"])
    return {
        "event_count": len(events),
        "event_types": dict(sorted(event_types.items())),
        "sentinel_observed": sentinel in "".join(text_parts),
        "done_observed": any(event.get("type") == "done" for event in events),
        "providers": sorted(providers),
        "models": sorted(models),
        "reasoning_efforts": sorted(reasoning_efforts),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--attestation", type=Path, required=True)
    parser.add_argument("--confirm", action="store_true")
    args = parser.parse_args()
    if not args.confirm:
        print(json.dumps({"status": "blocked", "reason": "confirmation-required"}))
        return 2
    if args.attestation.exists():
        raise FileExistsError("attestation path must be new")

    commands: dict[str, Any] = {}
    config, commands["config_show"] = _run_json("compozy", "config", "show", "-o", "json")
    providers = config.get("config", {}).get("providers", {})
    grok_config = providers.get(GROK_PROVIDER) if isinstance(providers, dict) else None
    if not isinstance(grok_config, dict) or not isinstance(providers.get(CODEX_PROVIDER), dict):
        raise RuntimeError("required Compozy providers are absent")
    grok_argv = validate_provider_config(grok_config)
    grok_executable = Path(grok_argv[0]).expanduser()
    if not grok_executable.is_absolute():
        resolved = shutil.which(str(grok_executable))
        if not resolved:
            raise RuntimeError("Grok CLI executable cannot be resolved")
        grok_executable = Path(resolved)
    grok_executable = grok_executable.resolve()

    planner_sentinel = "V12_PLAN_" + secrets.token_hex(10).upper()
    executor_sentinel = "V12_EXEC_" + secrets.token_hex(10).upper()
    handoff_id = "HANDOFF_" + secrets.token_hex(10).upper()
    before = _tree_sha(ROOT)
    pids_before = _matching_grok_pids()
    session_id: str | None = None
    planner_summary: dict[str, Any] = {}
    executor_summary: dict[str, Any] = {}
    cleanup: dict[str, Any] = {"active_session_residual": True}
    failure: str | None = None
    try:
        created, commands["session_new"] = _run_json(
            "compozy", "session", "new", "--cwd", str(ROOT), "--agent", "general",
            "--network", "local", "-o", "json",
        )
        session_id = str(created.get("id", ""))
        if not session_id:
            raise RuntimeError("Compozy returned no session id")

        planner_events, commands["planner_prompt"] = _run_json(
            "compozy", "session", "prompt", session_id,
            f"Read-only planning probe. Do not call tools. Reply exactly {planner_sentinel}.",
            "--provider", CODEX_PROVIDER, "--model", CODEX_MODEL,
            "--reasoning-effort", "low", "-o", "json",
        )
        if not isinstance(planner_events, list):
            raise RuntimeError("planner event stream is invalid")
        planner_summary = _summarize_turn(planner_events, planner_sentinel)
        if (
            not planner_summary["sentinel_observed"]
            or not planner_summary["done_observed"]
            or planner_summary["providers"] != [CODEX_PROVIDER]
            or planner_summary["models"] != [CODEX_MODEL]
        ):
            raise RuntimeError("Codex planner identity or completion was not observed")

        executor_events, commands["executor_prompt"] = _run_json(
            "compozy", "session", "prompt", session_id,
            f"Read-only executor handoff {handoff_id}. Do not call tools. Reply exactly {executor_sentinel}.",
            "--provider", GROK_PROVIDER, "-o", "json",
        )
        if not isinstance(executor_events, list):
            raise RuntimeError("executor event stream is invalid")
        executor_summary = _summarize_turn(executor_events, executor_sentinel)
        if (
            not executor_summary["sentinel_observed"]
            or not executor_summary["done_observed"]
            or executor_summary["providers"] != [GROK_PROVIDER]
        ):
            raise RuntimeError("Grok executor identity or completion was not observed")
    except Exception as exc:
        failure = f"{type(exc).__name__}: {exc}"
    finally:
        if session_id:
            stopped = subprocess.run(
                ("compozy", "session", "stop", session_id, "-o", "json"),
                capture_output=True, text=True, check=False, timeout=30,
            )
            commands["session_stop"] = {
                "returncode": stopped.returncode,
                "output_sha256": _sha(stopped.stdout + stopped.stderr),
            }
            cleanup["stop_returncode"] = stopped.returncode

    sessions, commands["session_list"] = _run_json("compozy", "session", "list", "-o", "json")
    active = sessions.get("sessions", []) if isinstance(sessions, dict) else []
    cleanup["active_session_residual"] = any(
        isinstance(item, dict) and item.get("id") == session_id for item in active
    )
    cleanup["new_grok_process_residual_count"] = len(_matching_grok_pids() - pids_before)
    after = _tree_sha(ROOT)
    passed = all((
        failure is None,
        cleanup.get("stop_returncode") == 0,
        not cleanup["active_session_residual"],
        cleanup["new_grok_process_residual_count"] == 0,
        before == after,
    ))
    document: dict[str, Any] = {
        "schema_version": "compozy-v1.2-topology-attestation",
        "protocol_version": "v1.2",
        "analysis_eligible": False,
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "status": "passed" if passed else "failed",
        "ade": "compozy",
        "topology": {
            "planner": {"provider": CODEX_PROVIDER, "model": CODEX_MODEL, "execution": planner_summary},
            "executor": {
                "provider": GROK_PROVIDER,
                "configured_model": GROK_MODEL,
                "runtime_reported_model_observed": False,
                "execution": executor_summary,
            },
            "same_session": True,
            "handoff_id_sha256": _sha(handoff_id),
            "fallback_used": False,
        },
        "provider_binding": {
            "transport": "acp-stdio",
            "grok_command_sha256": _sha("\0".join(grok_argv)),
            "grok_executable_sha256": sha256_bytes(grok_executable.read_bytes()),
        },
        "workspace": {"unchanged": before == after, "before_sha256": before, "after_sha256": after},
        "cleanup": cleanup,
        "commands": commands,
        "redaction": {
            "raw_prompt_persisted_publicly": False,
            "raw_model_output_persisted_publicly": False,
            "local_stopped_session_history_retained": True,
            "session_id_sha256": _sha(session_id or ""),
            "planner_sentinel_sha256": _sha(planner_sentinel),
            "executor_sentinel_sha256": _sha(executor_sentinel),
        },
        "limitations": [
            "The Grok model is process-argument-bound because ACP events do not report its model identity.",
            "Stopped Compozy session history remains local and is excluded from public evidence.",
        ],
        "source_hashes": {
            "controller/scripts/probe_compozy_v12_topology.py": sha256_bytes(Path(__file__).read_bytes()),
            "controller/src/benchmark_controller/compozy_grok.py": sha256_bytes((ROOT / "controller/src/benchmark_controller/compozy_grok.py").read_bytes()),
            "adapters/compozy-grok-cli-provider-v1.2.toml": sha256_bytes((ROOT / "adapters/compozy-grok-cli-provider-v1.2.toml").read_bytes()),
        },
    }
    if failure:
        document["failure"] = failure
    args.attestation.parent.mkdir(parents=True, exist_ok=True)
    args.attestation.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": document["status"], "attestation": str(args.attestation), "sha256": _sha(args.attestation.read_bytes())}))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
