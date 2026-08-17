#!/usr/bin/env python3
"""Run bounded, read-only ADE preflights and publish only redacted evidence."""

from __future__ import annotations

import hashlib
import json
import tempfile
from datetime import date
from pathlib import Path

from benchmark_controller.agent_orchestrator import AgentOrchestratorAdapter
from benchmark_controller.ledger import Ledger
from benchmark_controller.orca import OrcaAdapter


def _probe(name: str, factory, call, root: Path, directory: Path) -> dict[str, object]:
    ledger_path = directory / f"{name}.jsonl"
    ledger = Ledger(ledger_path, run_id=f"run_probe-{name}", task_id="pilot_ade-readonly")
    try:
        summary = call(factory(ledger))
        serialized = json.dumps(summary, sort_keys=True, separators=(",", ":"))
        result: dict[str, object] = {
            "status": "passed",
            "summary_sha256": hashlib.sha256(serialized.encode("utf-8")).hexdigest(),
        }
    except Exception as exc:
        result = {"status": "failed", "error_type": type(exc).__name__}
    result["ledger_events"] = sum(1 for _ in ledger_path.open(encoding="utf-8")) if ledger_path.exists() else 0
    result["agent_sessions_started"] = False
    return result


def main() -> int:
    root = Path.cwd()
    with tempfile.TemporaryDirectory(prefix="benchmark-ade-probe-") as directory:
        probe_dir = Path(directory)
        result = {
            "schema_version": "ade-readonly-attestation-v1.0",
            "verified_on": date.today().isoformat(),
            "workspace_scope": "current-repository-only",
            "side_effect_policy": {
                "agent_sessions_started": False,
                "workflows_started": False,
                "tasks_started": False,
                "raw_payloads_published": False,
            },
            "components": {
                "orca": _probe(
                    "orca",
                    lambda ledger: OrcaAdapter(root, ledger),
                    lambda adapter: adapter.read_only_preflight().to_dict(),
                    root,
                    probe_dir,
                ),
                "agent-orchestrator": _probe(
                    "agent-orchestrator",
                    lambda ledger: AgentOrchestratorAdapter(root, ledger),
                    lambda adapter: adapter.read_only_preflight(project_id="code-10x").to_dict(),
                    root,
                    probe_dir,
                ),
            },
        }
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if all(item["status"] == "passed" for item in result["components"].values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
