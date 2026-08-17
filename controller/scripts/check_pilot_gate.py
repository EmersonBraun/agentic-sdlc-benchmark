#!/usr/bin/env python3
"""Print the pilot gate and exit non-zero while any primary condition is blocked."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from benchmark_controller.pilot import evaluate_pilot_gate


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--preflight", type=Path, required=True)
    args = parser.parse_args()
    preflight = json.loads(args.preflight.read_text(encoding="utf-8"))
    report = evaluate_pilot_gate(preflight)
    print(json.dumps(report.to_dict(), indent=2, sort_keys=True))
    return 0 if report.can_start else 1


if __name__ == "__main__":
    raise SystemExit(main())

