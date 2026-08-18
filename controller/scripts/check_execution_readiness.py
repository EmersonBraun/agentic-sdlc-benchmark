#!/usr/bin/env python3
"""Print the deterministic operational readiness report for protocol v1.1."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "controller" / "src"))

from benchmark_controller.execution_readiness import evaluate_execution_readiness  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--preflight", type=Path, required=True)
    args = parser.parse_args()
    preflight = json.loads(args.preflight.read_text(encoding="utf-8"))
    report = evaluate_execution_readiness(preflight)
    print(json.dumps(report.to_dict(), indent=2, sort_keys=True))
    return 0 if report.can_start_official_collection else 1


if __name__ == "__main__":
    raise SystemExit(main())
