#!/usr/bin/env python3
"""Print deterministic component readiness from a frozen preflight document."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "controller" / "src"))

from benchmark_controller.readiness import evaluate_adapter_readiness  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--preflight", type=Path, required=True)
    args = parser.parse_args()
    report = evaluate_adapter_readiness(json.loads(args.preflight.read_text(encoding="utf-8")))
    print(json.dumps(report.to_dict(), indent=2, sort_keys=True))
    return 0 if report.blocked_components == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
