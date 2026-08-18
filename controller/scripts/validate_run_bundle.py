#!/usr/bin/env python3
"""Validate the public integrity boundary of one or more run bundles."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

_SHA256 = re.compile(r"^[a-f0-9]{64}$")
_RUN_ID = re.compile(r"^run_[A-Za-z0-9_-]+$")
_TASK_ID = re.compile(r"^(pilot|main|holdout)_[A-Za-z0-9_-]+$")
_STAGES = {
    "intake", "requirements", "planning", "decomposition", "implementation",
    "local-testing", "pull-request", "ci-qa", "review", "merge", "documentation",
}
_ACTORS = {
    "controller", "planner", "executor", "fixer", "reviewer-functional",
    "reviewer-security", "reviewer-qa", "oracle", "evaluator", "human-operator",
    "infrastructure",
}
_TIME_CATEGORIES = {
    "effective_work", "human_touch", "orchestration_overhead", "harness_overhead",
    "instrumentation_overhead", "external_wait",
}


def _error(errors: list[str], path: Path, message: str) -> None:
    errors.append(f"{path}: {message}")


def validate_bundle(directory: Path, tasks_root: Path, protocol: str) -> list[str]:
    errors: list[str] = []
    manifest_path = directory / "manifest.json"
    ledger_path = directory / "ledger.jsonl"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [f"{manifest_path}: {type(exc).__name__}"]
    if not isinstance(manifest, dict):
        return [f"{manifest_path}: expected object"]

    required = {
        "schema_version", "protocol_version", "run_id", "task_id",
        "task_manifest_sha256", "product_id", "condition_id", "replicate",
        "randomization_seed", "base_commit", "gate_mode", "analysis_eligible",
        "terminal_state", "artifacts",
    }
    for key in sorted(required - set(manifest)):
        _error(errors, manifest_path, f"missing {key}")
    if manifest.get("schema_version") != "1.1" or manifest.get("protocol_version") != protocol:
        _error(errors, manifest_path, "protocol/schema mismatch")
    run_id = manifest.get("run_id")
    task_id = manifest.get("task_id")
    if not isinstance(run_id, str) or not _RUN_ID.fullmatch(run_id):
        _error(errors, manifest_path, "invalid run_id")
    if not isinstance(task_id, str) or not _TASK_ID.fullmatch(task_id):
        _error(errors, manifest_path, "invalid task_id")
    if directory.name != run_id:
        _error(errors, manifest_path, "directory name does not match run_id")
    task_path = tasks_root / f"{task_id}.manifest.json" if isinstance(task_id, str) else None
    digest = manifest.get("task_manifest_sha256")
    if not isinstance(digest, str) or not _SHA256.fullmatch(digest):
        _error(errors, manifest_path, "invalid task_manifest_sha256")
    elif task_path is None or not task_path.is_file():
        _error(errors, manifest_path, "bound task manifest is missing")
    elif hashlib.sha256(task_path.read_bytes()).hexdigest() != digest:
        _error(errors, manifest_path, "task manifest hash mismatch")
    if not isinstance(manifest.get("replicate"), int) or manifest.get("replicate", 0) < 1:
        _error(errors, manifest_path, "replicate must be positive")
    if not isinstance(manifest.get("randomization_seed"), int) or manifest.get("randomization_seed", -1) < 0:
        _error(errors, manifest_path, "randomization_seed must be non-negative")
    if not isinstance(manifest.get("artifacts"), list):
        _error(errors, manifest_path, "artifacts must be an array")
    gate_mode = manifest.get("gate_mode")
    analysis_eligible = manifest.get("analysis_eligible")
    terminal_state = manifest.get("terminal_state")
    if gate_mode not in {"technical-pilot", "official-collection"}:
        _error(errors, manifest_path, "invalid gate_mode")
    if not isinstance(analysis_eligible, bool):
        _error(errors, manifest_path, "analysis_eligible must be boolean")
    if gate_mode == "technical-pilot":
        if analysis_eligible is not False:
            _error(errors, manifest_path, "technical pilot must be analysis-ineligible")
        if terminal_state not in {"NOT_APPLICABLE", "TECHNICAL_PASS", "TECHNICAL_FAIL"}:
            _error(errors, manifest_path, "invalid technical-pilot terminal_state")
    elif terminal_state in {"TECHNICAL_PASS", "TECHNICAL_FAIL"}:
        _error(errors, manifest_path, "technical terminal state on official collection")

    try:
        lines = ledger_path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        return errors + [f"{ledger_path}: {type(exc).__name__}"]
    for sequence, line in enumerate(lines, 1):
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            _error(errors, ledger_path, f"line {sequence} is not JSON")
            continue
        if not isinstance(event, dict):
            _error(errors, ledger_path, f"line {sequence} is not an object")
            continue
        if event.get("run_id") != run_id or event.get("task_id") != task_id:
            _error(errors, ledger_path, f"line {sequence} identity mismatch")
        if event.get("event_id") != f"evt_{sequence:06d}":
            _error(errors, ledger_path, f"line {sequence} sequence mismatch")
        if event.get("stage_id") not in _STAGES or event.get("actor") not in _ACTORS:
            _error(errors, ledger_path, f"line {sequence} invalid stage or actor")
        if event.get("time_category") not in _TIME_CATEGORIES:
            _error(errors, ledger_path, f"line {sequence} invalid time category")
        if event.get("status") not in {"started", "completed", "failed", "blocked", "redacted"}:
            _error(errors, ledger_path, f"line {sequence} invalid status")
        if not isinstance(event.get("duration_ms"), (int, float)) or event.get("duration_ms", -1) < 0:
            _error(errors, ledger_path, f"line {sequence} invalid duration")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs-root", type=Path, required=True)
    parser.add_argument("--tasks-root", type=Path, required=True)
    parser.add_argument("--protocol", default="v1.1")
    args = parser.parse_args()
    manifests = sorted(args.runs_root.glob("*/manifest.json"))
    errors: list[str] = []
    for manifest_path in manifests:
        errors.extend(validate_bundle(manifest_path.parent, args.tasks_root, args.protocol))
    print(json.dumps({"status": "valid" if not errors else "invalid", "bundles": len(manifests), "errors": errors}, indent=2, sort_keys=True))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
