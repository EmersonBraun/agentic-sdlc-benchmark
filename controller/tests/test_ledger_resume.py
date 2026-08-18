import json
import tempfile
import unittest
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from benchmark_controller.ledger import Ledger


def _record_concurrently(arguments: tuple[str, int]) -> None:
    path, index = arguments
    Ledger(Path(path), run_id="run_concurrent", task_id="pilot_concurrent").record(
        stage_id="implementation",
        actor="executor",
        event_type=f"worker.{index}",
        time_category="effective_work",
        duration_ms=1,
        status="completed",
    )


class LedgerResumeTests(unittest.TestCase):
    def test_concurrent_writers_allocate_unique_sequences(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ledger.jsonl"
            with ProcessPoolExecutor(max_workers=8) as pool:
                list(pool.map(_record_concurrently, [(str(path), index) for index in range(24)]))

            events = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
            event_ids = [event["event_id"] for event in events]
            self.assertEqual(len(event_ids), 24)
            self.assertEqual(len(set(event_ids)), 24)
            self.assertEqual(sorted(event_ids), [f"evt_{index:06d}" for index in range(1, 25)])

    def test_independent_writer_resumes_append_only_sequence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ledger.jsonl"
            first = Ledger(path, run_id="run_resume", task_id="pilot_resume")
            first.record(
                stage_id="intake",
                actor="controller",
                event_type="first",
                time_category="instrumentation_overhead",
                duration_ms=0,
                status="completed",
            )
            second = Ledger(path, run_id="run_resume", task_id="pilot_resume")
            second.record(
                stage_id="implementation",
                actor="executor",
                event_type="second",
                time_category="effective_work",
                duration_ms=1,
                status="completed",
            )
            first.record(
                stage_id="documentation",
                actor="controller",
                event_type="third",
                time_category="instrumentation_overhead",
                duration_ms=0,
                status="completed",
            )

            events = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
            self.assertEqual([event["event_id"] for event in events], ["evt_000001", "evt_000002", "evt_000003"])

    def test_rejects_existing_ledger_for_another_run(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ledger.jsonl"
            Ledger(path, run_id="run_one", task_id="pilot_one").record(
                stage_id="intake",
                actor="controller",
                event_type="first",
                time_category="instrumentation_overhead",
                duration_ms=0,
                status="completed",
            )
            with self.assertRaisesRegex(ValueError, "different run"):
                Ledger(path, run_id="run_two", task_id="pilot_one")


if __name__ == "__main__":
    unittest.main()
