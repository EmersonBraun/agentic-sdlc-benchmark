#!/usr/bin/env python3
"""Run the reproducible ORCA terminal-ready lifecycle settlement probe."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "controller/src"))

from benchmark_controller.ledger import Ledger  # noqa: E402
from benchmark_controller.orca import OrcaAdapter  # noqa: E402

IGNORED = {".git", ".next", ".DS_Store", "node_modules"}


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def tree_sha256(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        if any(part in IGNORED for part in relative.parts):
            continue
        digest.update(str(relative).encode())
        if path.is_symlink():
            digest.update(b"symlink\0" + str(path.readlink()).encode())
        elif path.is_file():
            digest.update(b"file\0" + path.read_bytes())
        else:
            digest.update(b"dir\0")
    return digest.hexdigest()


def nested(document: dict[str, Any], *keys: str) -> Any:
    value: Any = document
    for key in keys:
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    return value


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--confirm", action="store_true")
    parser.add_argument("--observation", type=Path, required=True)
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument("--timeout-seconds", type=int, default=300)
    args = parser.parse_args()
    if not args.confirm:
        print(json.dumps({"executable": False, "reason": "operator confirmation required"}))
        return 2
    if args.observation.exists() or args.ledger.exists():
        raise FileExistsError("observation and ledger paths must be new")

    workspace = ROOT
    before = tree_sha256(workspace)
    ledger = Ledger(args.ledger, run_id="run_orca-lifecycle-readiness", task_id="pilot_smoke")
    adapter = OrcaAdapter(workspace, ledger, permission_mode="approve-all")
    coordinator: str | None = None
    worker: str | None = None
    run_id: str | None = None
    task_id: str | None = None
    dispatch_id: str | None = None
    capability_hash: str | None = None
    delivery_acknowledged = False
    terminal_wait: dict[str, Any] = {}
    status = "failed"
    error: str | None = None
    try:
        current = adapter._json_command(("status", "--json"), stage_id="intake")
        created_coordinator = adapter._json_command(
            ("terminal", "create", "--worktree", "active", "--title", "benchmark-orca-coordinator",
             "--command", "zsh", "--json"), stage_id="intake", access="write",
        )
        coordinator = nested(created_coordinator, "result", "terminal", "handle")
        if not isinstance(coordinator, str):
            raise RuntimeError("coordinator terminal handle missing")
        run = adapter.start_workflow(objective="ORCA v1.1 lifecycle settlement probe", coordinator_handle=coordinator)
        run_id = nested(run, "result", "run", "id")
        if not isinstance(run_id, str):
            raise RuntimeError("run id missing")
        task = adapter.create_task(
            run_id=run_id, coordinator_handle=coordinator, title="Lifecycle settlement probe",
            spec="Read-only. Report ORCA_LIFECYCLE_READY and send worker_done once without file changes.",
        )
        task_id = nested(task, "result", "task", "id")
        if not isinstance(task_id, str):
            raise RuntimeError("task id missing")
        started = adapter.start_ready_dispatch(
            task_id=task_id, coordinator_handle=coordinator,
            agent_command="codex --dangerously-bypass-approvals-and-sandbox -m gpt-5.4 -c model_reasoning_effort=medium",
            timeout_ms=120000,
        )
        worker = started["terminal_handle"]
        dispatch_id = nested(started["dispatch"], "result", "dispatch", "id")
        settled = adapter.await_settlement(
            task_id=task_id, terminal_handle=worker, timeout_seconds=args.timeout_seconds,
        )
        dispatch = settled["dispatch"]
        capability_hash = dispatch.get("capability_hash")
        delivery = settled["delivery"]
        messages = nested(delivery, "result", "messages")
        delivery_id = nested(delivery, "result", "deliveryId")
        if not isinstance(messages, list) or not any(message.get("type") == "worker_done" for message in messages):
            raise RuntimeError("accepted worker_done delivery missing")
        if not isinstance(delivery_id, str):
            raise RuntimeError("delivery id missing")
        delivery_acknowledged = True
        worker = None
        terminal_wait = {"condition": "tui-idle", "satisfied": True, "status": "running"}
        status = "passed"
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
    finally:
        for handle in (worker, coordinator):
            if isinstance(handle, str):
                adapter._json_command(
                    ("terminal", "close", "--terminal", handle, "--json"),
                    stage_id="documentation", access="write", allow_failure=True,
                )

    observation: dict[str, Any] = {
        "schema_version": "orca-lifecycle-observation-v1.1",
        "status": status,
        "runtime_version": "1.4.184",
        "model": "gpt-5.4",
        "reasoning_effort": "medium",
        "terminal_wait": terminal_wait,
        "dispatch": {
            "id_sha256": sha256_text(dispatch_id or ""), "capability_hash": capability_hash,
            "status": "completed" if status == "passed" else "failed",
        },
        "delivery": {
            "type": "worker_done", "task_id_sha256": sha256_text(task_id or ""),
            "dispatch_id_sha256": sha256_text(dispatch_id or ""), "acknowledged": delivery_acknowledged,
        },
        "cleanup": {"workspace_tree_unchanged": tree_sha256(workspace) == before},
        "redaction": {"raw_model_output_persisted": False, "dispatch_capability_persisted": False},
    }
    if error:
        observation["error"] = error
    args.observation.write_text(json.dumps(observation, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": status, "observation": str(args.observation)}))
    return 0 if status == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
