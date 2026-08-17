import json
import tempfile
import unittest
from pathlib import Path

from aggregate_runs import aggregate


class AggregateRunsTests(unittest.TestCase):
    def test_empty_runs_are_explicitly_no_results(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            report = aggregate(runs_root=root / "runs", tasks_root=root / "tasks", protocol_version="v1.1")
            self.assertEqual(report["status"], "no-results")
            self.assertEqual(report["summary"]["runs"], 0)
            self.assertIsNone(report["metrics"]["effective_work_hours"]["median"])

    def test_effective_work_speedup_and_quality_are_aggregated(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            tasks = root / "tasks"
            tasks.mkdir()
            (tasks / "task.manifest.json").write_text(json.dumps({
                "task_id": "pilot_task",
                "baseline": {"pert_expected_hours": 6},
            }), encoding="utf-8")
            run = root / "runs" / "run_one"
            run.mkdir(parents=True)
            (run / "manifest.json").write_text(json.dumps({
                "run_id": "run_one",
                "task_id": "pilot_task",
                "product_id": "greenfield",
                "protocol_version": "v1.1",
                "condition_id": "orca__reference__off",
                "replicate": 1,
                "terminal_state": "MERGED",
            }), encoding="utf-8")
            (run / "ledger.jsonl").write_text(
                json.dumps({"event_id": "evt_1", "run_id": "run_one", "task_id": "pilot_task", "stage_id": "implementation", "time_category": "effective_work", "duration_ms": 3_600_000, "status": "completed"}) + "\n",
                encoding="utf-8",
            )
            (run / "evaluation-result.json").write_text(json.dumps({
                "schema_version": "1.0",
                "run_id": "run_one",
                "quality_pass": True,
                "product_quality_score": 92,
                "process_score": 88,
                "hard_gates": {"tests": True},
                "evaluator_status": "complete",
            }), encoding="utf-8")
            report = aggregate(runs_root=root / "runs", tasks_root=tasks, protocol_version="v1.1")
            self.assertEqual(report["status"], "complete")
            self.assertEqual(report["summary"]["runs"], 1)
            self.assertEqual(report["metrics"]["effective_work_hours"]["median"], 1.0)
            self.assertEqual(report["metrics"]["speedup_vs_baseline"]["median"], 6.0)
            self.assertEqual(report["metrics"]["quality_score"]["median"], 92.0)


if __name__ == "__main__":
    unittest.main()
