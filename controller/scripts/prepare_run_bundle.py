#!/usr/bin/env python3
"""Prepare one immutable run bundle, or fail before creating any run data."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "controller" / "src"))

from benchmark_controller.pilot_executor import PilotNotReadyError  # noqa: E402
from benchmark_controller.run_bundles import RunBundleError, RunBundleWriter  # noqa: E402


def _json_object(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected a JSON object: {path}")
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--preflight", type=Path, required=True)
    parser.add_argument("--tasks-root", type=Path, required=True)
    parser.add_argument("--runs-root", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--product", dest="product_id", required=True)
    parser.add_argument("--ade", required=True)
    parser.add_argument("--harness", required=True)
    parser.add_argument("--agentskit", choices=("off", "on"), required=True)
    parser.add_argument("--replicate", type=int, required=True)
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--base-commit", required=True)
    parser.add_argument("--models", type=Path, required=True, help="JSON object of role-to-snapshot IDs")
    parser.add_argument("--components", type=Path, required=True, help="JSON object of component versions")
    parser.add_argument("--environment", type=Path, help="Optional JSON environment snapshot")
    parser.add_argument("--budgets", type=Path, help="Optional JSON budget snapshot")
    args = parser.parse_args()

    try:
        writer = RunBundleWriter(
            _json_object(args.preflight),
            args.runs_root,
            tasks_root=args.tasks_root,
        )
        prepared = writer.create(
            run_id=args.run_id,
            task_id=args.task_id,
            product_id=args.product_id,
            ade=args.ade,
            harness=args.harness,
            agentskit=args.agentskit,
            replicate=args.replicate,
            randomization_seed=args.seed,
            base_commit=args.base_commit,
            model_snapshots=_json_object(args.models),
            component_versions=_json_object(args.components),
            environment=_json_object(args.environment) if args.environment else None,
            budgets=_json_object(args.budgets) if args.budgets else None,
        )
    except (OSError, ValueError, PilotNotReadyError, RunBundleError) as exc:
        print(json.dumps({"status": "blocked", "error": str(exc)}, sort_keys=True))
        return 1

    print(json.dumps({"status": "prepared", "run_id": prepared.manifest["run_id"], "directory": str(prepared.directory)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
