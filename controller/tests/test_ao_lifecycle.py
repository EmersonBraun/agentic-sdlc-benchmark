import tempfile
import unittest
from pathlib import Path

from benchmark_controller.ao_lifecycle import SessionLifecycleObserver, normalize_session_snapshot
from benchmark_controller.external import LifecycleBridge
from benchmark_controller.ledger import Ledger


class AgentOrchestratorLifecycleTests(unittest.TestCase):
    def test_normalizes_working_state_exposed_by_current_runtime(self) -> None:
        event = normalize_session_snapshot({"id": "session-1", "status": "working"})
        self.assertEqual(event["status"], "started")
        self.assertEqual(event["snapshot_state"], "working")

    def test_normalizes_and_redacts_session_state(self) -> None:
        event = normalize_session_snapshot({"id": "session-private", "status": "running"})
        self.assertEqual(event["status"], "started")
        self.assertEqual(event["snapshot_state"], "running")

    def test_observer_deduplicates_public_state_snapshots(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ledger = Ledger(root / "ledger.jsonl", run_id="run_ao-lifecycle", task_id="pilot_smoke")
            observer = SessionLifecycleObserver(LifecycleBridge(ledger, tool="agent-orchestrator"))
            first = observer.observe({"id": "session-private", "status": "running"})
            duplicate = observer.observe({"id": "session-private", "status": "running"})
            terminal = observer.observe({"id": "session-private", "status": "terminated"})
            self.assertIsNotNone(first)
            self.assertIsNone(duplicate)
            self.assertIsNotNone(terminal)
            self.assertEqual(len((root / "ledger.jsonl").read_text().splitlines()), 2)
            content = (root / "ledger.jsonl").read_text()
            self.assertNotIn("session-private", content)
