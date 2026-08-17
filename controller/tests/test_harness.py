import json
import tempfile
import unittest
from pathlib import Path

from benchmark_controller.harness import ReferenceHarness
from benchmark_controller.ledger import Ledger


class ReferenceHarnessTests(unittest.TestCase):
    def test_runs_argv_and_records_ledger_event(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ledger = Ledger(root / "ledger.jsonl", run_id="run_harness", task_id="pilot_smoke")
            harness = ReferenceHarness(root / "workspace", ledger)
            result = harness.run(
                ["python3", "-c", "print('ok')"],
                stage_id="local-testing",
                actor="executor",
            )

            self.assertEqual(result.returncode, 0)
            self.assertEqual(result.stdout.strip(), "ok")
            events = [json.loads(line) for line in (root / "ledger.jsonl").read_text().splitlines()]
            self.assertEqual([event["event_type"] for event in events], ["workspace.prepared", "command.executed"])
            self.assertEqual(events[-1]["time_category"], "effective_work")

    def test_timeout_is_recorded_without_raising(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ledger = Ledger(root / "ledger.jsonl", run_id="run_timeout", task_id="pilot_smoke")
            harness = ReferenceHarness(root / "workspace", ledger)
            result = harness.run(
                ["python3", "-c", "import time; time.sleep(0.05)"],
                stage_id="implementation",
                actor="executor",
                timeout_seconds=0.001,
            )

            self.assertTrue(result.timed_out)
            event = json.loads((root / "ledger.jsonl").read_text().splitlines()[-1])
            self.assertEqual(event["status"], "failed")
            self.assertTrue(event["payload_sha256"])

    def test_artifact_hash_rejects_path_escape(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ledger = Ledger(root / "ledger.jsonl", run_id="run_hash", task_id="pilot_smoke")
            harness = ReferenceHarness(root / "workspace", ledger)
            harness.prepare()
            with self.assertRaises(ValueError):
                harness.hash_file("../outside")
