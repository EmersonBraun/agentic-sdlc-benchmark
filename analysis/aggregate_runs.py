#!/usr/bin/env python3
"""Aggregate redacted benchmark run bundles into reproducible analysis data."""

from __future__ import annotations

import argparse
import json
import random
import sys
from datetime import datetime
from pathlib import Path
from statistics import median
from typing import Any, Iterable

_REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(_REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPOSITORY_ROOT))

from evaluation.validate_result import validate_result


def _percentile(values: list[float], probability: float) -> float:
    if not values:
        raise ValueError("percentile requires values")
    ordered = sorted(values)
    position = (len(ordered) - 1) * probability
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


def _iqr(values: list[float]) -> float | None:
    if not values:
        return None
    return _percentile(values, 0.75) - _percentile(values, 0.25)


def _bootstrap_median_ci(values: list[float], *, seed: int, iterations: int = 2000) -> list[float] | None:
    if len(values) < 2:
        return None
    rng = random.Random(seed)
    samples = [median(rng.choices(values, k=len(values))) for _ in range(iterations)]
    return [round(_percentile(samples, 0.025), 6), round(_percentile(samples, 0.975), 6)]


def summarize_values(values: Iterable[float], *, seed: int) -> dict[str, Any]:
    numeric = [float(value) for value in values]
    if not numeric:
        return {"n": 0, "median": None, "minimum": None, "maximum": None, "iqr": None, "bootstrap_ci_95": None}
    return {
        "n": len(numeric),
        "median": round(median(numeric), 6),
        "minimum": round(min(numeric), 6),
        "maximum": round(max(numeric), 6),
        "iqr": round(_iqr(numeric) or 0, 6),
        "bootstrap_ci_95": _bootstrap_median_ci(numeric, seed=seed),
    }


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected an object: {path}")
    return value


def _load_baselines(tasks_root: Path) -> dict[str, float]:
    baselines: dict[str, float] = {}
    for path in sorted(tasks_root.rglob("*.manifest.json")):
        manifest = _load_json(path)
        task_id = manifest.get("task_id")
        expected = manifest.get("baseline", {}).get("pert_expected_hours")
        if isinstance(task_id, str) and isinstance(expected, (int, float)) and expected > 0:
            baselines[task_id] = float(expected)
    return baselines


def _load_ledger(path: Path) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    if not path.exists():
        return events
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        event = json.loads(line)
        if not isinstance(event, dict):
            raise ValueError(f"Ledger line {line_number} is not an object: {path}")
        required = {"event_id", "run_id", "task_id", "stage_id", "time_category", "duration_ms", "status"}
        missing = sorted(required - set(event))
        if missing:
            raise ValueError(f"Ledger line {line_number} missing {missing}: {path}")
        events.append(event)
    return events


def _find_evaluation(directory: Path) -> dict[str, Any] | None:
    for filename in ("evaluation-result.json", "evaluation.json"):
        path = directory / filename
        if path.exists():
            result = _load_json(path)
            errors = validate_result(result, expected_run_id=result.get("run_id"))
            if errors:
                raise ValueError(f"Invalid evaluation result {path}: {','.join(errors)}")
            return result
    return None


def _run_record(directory: Path, baselines: dict[str, float]) -> dict[str, Any]:
    manifest = _load_json(directory / "manifest.json")
    events = _load_ledger(directory / "ledger.jsonl")
    evaluation = _find_evaluation(directory)
    durations: dict[str, float] = {}
    for event in events:
        category = event.get("time_category")
        duration = event.get("duration_ms")
        if isinstance(category, str) and isinstance(duration, (int, float)) and duration >= 0:
            durations[category] = durations.get(category, 0.0) + float(duration)
    effective_work_hours = durations.get("effective_work", 0.0) / 3_600_000
    baseline_hours = baselines.get(str(manifest.get("task_id")))
    speedup = baseline_hours / effective_work_hours if baseline_hours and effective_work_hours > 0 else None
    return {
        "run_id": manifest.get("run_id"),
        "task_id": manifest.get("task_id"),
        "product_id": manifest.get("product_id"),
        "protocol_version": manifest.get("protocol_version"),
        "condition_id": manifest.get("condition_id"),
        "replicate": manifest.get("replicate"),
        "terminal_state": manifest.get("terminal_state"),
        "event_count": len(events),
        "time_by_category_ms": {key: round(value, 3) for key, value in sorted(durations.items())},
        "effective_work_hours": round(effective_work_hours, 6),
        "baseline_expected_hours": baseline_hours,
        "speedup_vs_baseline": round(speedup, 6) if speedup is not None else None,
        "quality_score": evaluation.get("product_quality_score") if evaluation else None,
        "quality_pass": evaluation.get("quality_pass") if evaluation else None,
        "evaluation_status": evaluation.get("evaluator_status", "missing") if evaluation else "missing",
    }


def _metric(records: list[dict[str, Any]], field: str, *, seed: int) -> dict[str, Any]:
    return summarize_values(
        [record[field] for record in records if isinstance(record.get(field), (int, float))],
        seed=seed,
    )


def aggregate(*, runs_root: Path, tasks_root: Path, protocol_version: str, seed: int = 20260817) -> dict[str, Any]:
    baselines = _load_baselines(tasks_root)
    records: list[dict[str, Any]] = []
    invalid_runs: list[dict[str, str]] = []
    if runs_root.exists():
        for manifest_path in sorted(runs_root.glob("*/manifest.json")):
            try:
                record = _run_record(manifest_path.parent, baselines)
                if record["protocol_version"] != protocol_version:
                    invalid_runs.append({"path": str(manifest_path), "reason": "protocol_version_mismatch"})
                    continue
                records.append(record)
            except (OSError, ValueError, json.JSONDecodeError) as exc:
                invalid_runs.append({"path": str(manifest_path), "reason": type(exc).__name__})

    by_condition: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        by_condition.setdefault(str(record["condition_id"]), []).append(record)
    condition_reports = []
    for condition_id, condition_records in sorted(by_condition.items()):
        condition_reports.append({
            "condition_id": condition_id,
            "runs": len(condition_records),
            "metrics": {
                "effective_work_hours": _metric(condition_records, "effective_work_hours", seed=seed),
                "speedup_vs_baseline": _metric(condition_records, "speedup_vs_baseline", seed=seed + 1),
                "quality_score": _metric(condition_records, "quality_score", seed=seed + 2),
            },
        })

    evaluated = [record for record in records if record["evaluation_status"] in {"complete", "abstain", "invalid"}]
    quality_pass_count = sum(record["quality_pass"] is True for record in records)
    return {
        "schema_version": "analysis-results-v1.1",
        "protocol_version": protocol_version,
        "status": "no-results" if not records else "partial" if invalid_runs or len(evaluated) < len(records) else "complete",
        "generated_at": datetime.now().astimezone().isoformat(),
        "source": {"runs_root": str(runs_root), "tasks_root": str(tasks_root), "baseline_count": len(baselines), "bootstrap_seed": seed},
        "summary": {
            "runs": len(records),
            "evaluated_runs": len(evaluated),
            "quality_pass_count": quality_pass_count,
            "invalid_runs": len(invalid_runs),
        },
        "metrics": {
            "effective_work_hours": _metric(records, "effective_work_hours", seed=seed),
            "speedup_vs_baseline": _metric(records, "speedup_vs_baseline", seed=seed + 1),
            "quality_score": _metric(records, "quality_score", seed=seed + 2),
        },
        "by_condition": condition_reports,
        "records": records,
        "invalid_runs": invalid_runs,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs-root", type=Path, required=True)
    parser.add_argument("--tasks-root", type=Path, required=True)
    parser.add_argument("--protocol", default="v1.1")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = aggregate(runs_root=args.runs_root, tasks_root=args.tasks_root, protocol_version=args.protocol)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "runs": report["summary"]["runs"], "output": str(args.output)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
