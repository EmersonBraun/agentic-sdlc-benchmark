#!/usr/bin/env python3
"""Probe ORCA capability-bound dispatch to a native Grok 4.5 worker."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "controller/src"))

from benchmark_controller.ledger import Ledger  # noqa: E402
from benchmark_controller.orca import OrcaAdapter  # noqa: E402

ORCA = Path("/usr/local/bin/orca")
GROK = Path.home() / ".grok/bin/grok"
EXPECTED_ORCA_VERSION = "1.4.184"


def _sha(value: bytes | str) -> str:
    if isinstance(value, str):
        value = value.encode()
    return hashlib.sha256(value).hexdigest()


def _nested(document: dict[str, Any], *keys: str) -> Any:
    value: Any = document
    for key in keys:
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    return value


def _git_status() -> str:
    return subprocess.run(
        ("git", "status", "--porcelain", "--untracked-files=all"), cwd=ROOT,
        check=True, capture_output=True, text=True,
    ).stdout


def _unexpected_status(*allowed: Path) -> str:
    allowed_relative = {
        str(path.resolve().relative_to(ROOT))
        for path in allowed
        if path.resolve().is_relative_to(ROOT)
    }
    return "\n".join(
        line for line in _git_status().splitlines()
        if len(line) <= 3 or line[3:] not in allowed_relative
    )


def _terminal_handles(adapter: OrcaAdapter) -> set[str]:
    document = adapter._json_command(
        ("terminal", "list", "--worktree", adapter._workspace_selector(), "--limit", "100", "--json"),
        stage_id="intake",
    )
    terminals = _nested(document, "result", "terminals")
    if not isinstance(terminals, list):
        raise RuntimeError("ORCA terminal inventory is unavailable")
    return {
        str(item["handle"])
        for item in terminals
        if isinstance(item, dict) and isinstance(item.get("handle"), str) and item.get("connected") is not False
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--attestation", type=Path, required=True)
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument("--confirm", action="store_true")
    parser.add_argument("--allow-host-control", action="store_true")
    parser.add_argument("--timeout-seconds", type=int, default=300)
    args = parser.parse_args()
    if not args.confirm or not args.allow_host_control:
        print(json.dumps({"status": "blocked", "reason": "authorization-required"}))
        return 2
    if args.attestation.exists() or args.ledger.exists():
        raise FileExistsError("probe outputs must be new")
    if _git_status():
        raise RuntimeError("ORCA live probe requires a clean committed workspace")

    result: dict[str, Any] = {
        "schema_version": "orca-grok-v1.2-readiness-attestation",
        "protocol_version": "v1.2",
        "analysis_eligible": False,
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "ade": "orca",
        "role": "executor_fixer",
        "provider": "grok-cli",
        "configured_model": "grok-4.5",
        "reasoning_effort": "high",
        "transport": "orca-terminal-ready-capability-dispatch",
        "raw_content_persisted": False,
        "orchestration": {},
        "cleanup": {},
        "source_hashes": {
            "probe": _sha(Path(__file__).read_bytes()),
            "orca_adapter": _sha((ROOT / "controller/src/benchmark_controller/orca.py").read_bytes()),
            "orca_executable": _sha(ORCA.resolve().read_bytes()),
            "grok_executable": _sha(GROK.resolve().read_bytes()),
        },
    }
    coordinator: str | None = None
    worker: str | None = None
    baseline: set[str] = set()
    with tempfile.TemporaryDirectory(prefix="agentic-sdlc-orca-grok-v12-") as directory:
        temporary_ledger = Path(directory) / "ledger.jsonl"
        ledger = Ledger(temporary_ledger, run_id="run_orca-grok-v12-readiness", task_id="pilot_smoke")
        adapter = OrcaAdapter(ROOT, ledger, permission_mode="approve-all")
        try:
            status = adapter._json_command(("status", "--json"), stage_id="intake")
            runtime_ready = _nested(status, "result", "runtime", "state") == "ready"
            graph_ready = _nested(status, "result", "graph", "state") == "ready"
            runtime_version = _nested(status, "result", "runtime", "appVersion")
            result["runtime"] = {
                "ready": runtime_ready,
                "graph_ready": graph_ready,
                "version": runtime_version,
            }
            if not runtime_ready or not graph_ready or runtime_version != EXPECTED_ORCA_VERSION:
                raise RuntimeError("ORCA runtime does not match the frozen ready state")
            baseline = _terminal_handles(adapter)
            coordinator = adapter.create_coordinator_terminal(title="benchmark-v12-orca-coordinator")
            run = adapter.start_workflow(
                objective="Protocol v1.2 ORCA to Grok 4.5 readiness probe",
                coordinator_handle=coordinator,
            )
            run_id = _nested(run, "result", "run", "id")
            if not isinstance(run_id, str):
                raise RuntimeError("ORCA run identity missing")
            task = adapter.create_task(
                run_id=run_id,
                coordinator_handle=coordinator,
                title="Grok 4.5 capability probe",
                spec=(
                    "Read-only protocol probe. Do not edit files or run tools. "
                    "Report V12_ORCA_GROK45_READY and settle this Dispatch with worker_done exactly once."
                ),
            )
            task_id = _nested(task, "result", "task", "id")
            if not isinstance(task_id, str):
                raise RuntimeError("ORCA task identity missing")
            started = adapter.start_ready_dispatch(
                task_id=task_id,
                coordinator_handle=coordinator,
                agent_command="grok --model grok-4.5 --reasoning-effort high --always-approve",
                title="benchmark-v12-grok45-worker",
                timeout_ms=120000,
            )
            worker = str(started["terminal_handle"])
            settled = adapter.await_settlement(
                task_id=task_id, terminal_handle=worker, timeout_seconds=args.timeout_seconds,
            )
            worker = None
            dispatch = settled["dispatch"]
            delivery = settled["delivery"]
            result["orchestration"] = {
                "run_id_sha256": _sha(run_id),
                "task_id_sha256": _sha(task_id),
                "dispatch_id_sha256": _sha(str(dispatch.get("id", ""))),
                "dispatch_status": dispatch.get("status"),
                "failure_count": dispatch.get("failure_count"),
                "capability_hash_present": bool(dispatch.get("capability_hash")),
                "capability_revoked": bool(dispatch.get("capability_revoked_at")),
                "worker_done_accepted": any(
                    isinstance(item, dict) and item.get("type") == "worker_done"
                    for item in (_nested(delivery, "result", "messages") or [])
                ),
                "delivery_acknowledged": _nested(settled["acknowledged"], "ok") is True,
            }
            result["status"] = "passed" if all((
                result["orchestration"]["dispatch_status"] == "completed",
                result["orchestration"]["failure_count"] == 0,
                result["orchestration"]["capability_hash_present"],
                result["orchestration"]["capability_revoked"],
                result["orchestration"]["worker_done_accepted"],
                result["orchestration"]["delivery_acknowledged"],
            )) else "failed"
        except Exception as exc:
            result["status"] = "failed"
            result["failure"] = {"error_type": type(exc).__name__, "reason": str(exc)}
        finally:
            for handle in (worker, coordinator):
                if handle:
                    try:
                        adapter.close_terminal_verified(handle=handle, stage_id="documentation")
                    except Exception as exc:
                        result["status"] = "failed"
                        result.setdefault("cleanup_errors", []).append(type(exc).__name__)
            residual = _terminal_handles(adapter) - baseline
            result["cleanup"] = {"terminal_residual_count": len(residual), "verified": not residual}
            if residual:
                result["status"] = "failed"
            args.ledger.parent.mkdir(parents=True, exist_ok=True)
            args.ledger.write_bytes(temporary_ledger.read_bytes())

    unexpected_status = _unexpected_status(args.ledger, args.attestation)
    result["workspace"] = {
        "clean": unexpected_status == "",
        "status_sha256": _sha(unexpected_status),
    }
    if not result["workspace"]["clean"]:
        result["status"] = "failed"
    result["ledger_sha256"] = _sha(args.ledger.read_bytes())
    result["versions"] = {
        "grok": subprocess.run((str(GROK), "--version"), check=True, capture_output=True, text=True).stdout.strip(),
        "orca": EXPECTED_ORCA_VERSION,
    }
    args.attestation.parent.mkdir(parents=True, exist_ok=True)
    args.attestation.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": result["status"], "attestation": str(args.attestation), "sha256": _sha(args.attestation.read_bytes())}))
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
