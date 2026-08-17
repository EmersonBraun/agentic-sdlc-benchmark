#!/usr/bin/env python3
"""Print the deterministic v1.1 pilot schedule without starting collection."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "controller" / "src"))

from benchmark_controller.conditions import load_conditions  # noqa: E402
from benchmark_controller.matrix import build_pilot_schedule  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--conditions", type=Path, required=True)
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--product", dest="product_id", required=True)
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--replicates", type=int, default=1)
    args = parser.parse_args()

    document = load_conditions(args.conditions)
    if document.get("protocol_version") != "v1.1":
        raise SystemExit("pilot planner requires protocol v1.1")
    schedule = build_pilot_schedule(
        task_id=args.task_id,
        product_id=args.product_id,
        seed=args.seed,
        replicate_count=args.replicates,
    )
    print(json.dumps({
        "status": "planned",
        "protocol_version": "v1.1",
        "conditions": 18,
        "replicates_per_condition": args.replicates,
        "runs": len(schedule),
        "schedule": [item.to_dict() for item in schedule],
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
