#!/usr/bin/env python3
"""Validate one public, redacted evaluator result without exposing hidden tests."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def validate_result(result: dict[str, Any], *, expected_run_id: str | None = None) -> list[str]:
    errors: list[str] = []
    required = {"schema_version", "run_id", "quality_pass", "product_quality_score", "process_score", "hard_gates", "evaluator_status"}
    errors.extend(f"missing:{key}" for key in sorted(required - set(result)))
    if result.get("schema_version") != "1.0":
        errors.append("schema_version:must be 1.0")
    run_id = result.get("run_id")
    if not isinstance(run_id, str) or not run_id.startswith("run_"):
        errors.append("run_id:invalid")
    if expected_run_id is not None and run_id != expected_run_id:
        errors.append("run_id:mismatch")
    if not isinstance(result.get("quality_pass"), bool):
        errors.append("quality_pass:must be boolean")
    for field in ("product_quality_score", "process_score"):
        value = result.get(field)
        if not isinstance(value, (int, float)) or isinstance(value, bool) or not 0 <= value <= 100:
            errors.append(f"{field}:must be a number from 0 to 100")
    hard_gates = result.get("hard_gates")
    if not isinstance(hard_gates, dict) or not hard_gates or not all(isinstance(value, bool) for value in hard_gates.values()):
        errors.append("hard_gates:must be a non-empty boolean object")
    status = result.get("evaluator_status")
    if status not in {"complete", "abstain", "invalid"}:
        errors.append("evaluator_status:invalid")

    hidden = result.get("hidden_test_summary")
    if hidden is not None:
        if not isinstance(hidden, dict):
            errors.append("hidden_test_summary:must be an object")
        else:
            counts = {key: hidden.get(key) for key in ("total", "passed", "failed") if key in hidden}
            if counts and set(counts) != {"total", "passed", "failed"}:
                errors.append("hidden_test_summary:total/passed/failed must appear together")
            if counts and (not all(isinstance(value, int) and not isinstance(value, bool) and value >= 0 for value in counts.values()) or counts["passed"] + counts["failed"] > counts["total"]):
                errors.append("hidden_test_summary:invalid counts")
    notes = result.get("evaluator_notes")
    if notes is not None and (not isinstance(notes, list) or not all(isinstance(note, str) for note in notes)):
        errors.append("evaluator_notes:must be a string array")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("result", type=Path)
    parser.add_argument("--run-id")
    args = parser.parse_args()
    try:
        result = json.loads(args.result.read_text(encoding="utf-8"))
        errors = validate_result(result, expected_run_id=args.run_id) if isinstance(result, dict) else ["result:must be an object"]
    except (OSError, json.JSONDecodeError) as exc:
        errors = [f"read:{type(exc).__name__}"]
    if errors:
        print(json.dumps({"valid": False, "errors": errors}, sort_keys=True))
        return 1
    print(json.dumps({"valid": True, "run_id": result["run_id"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
