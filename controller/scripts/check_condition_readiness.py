#!/usr/bin/env python3
"""Print the factor-level readiness matrix for all 18 primary conditions."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "controller" / "src"))

from benchmark_controller.pilot import evaluate_pilot_gate  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--preflight", type=Path, required=True)
    args = parser.parse_args()
    report = evaluate_pilot_gate(json.loads(args.preflight.read_text(encoding="utf-8")))
    output = {
        "schema_version": f"condition-readiness-{report.protocol_version}",
        "protocol_version": report.protocol_version,
        "source": str(args.preflight),
        **report.to_dict(),
    }
    print(json.dumps(output, indent=2, sort_keys=True))
    return 0 if report.can_start else 1


if __name__ == "__main__":
    raise SystemExit(main())
