import json
import tempfile
import unittest
from pathlib import Path

from benchmark_controller.external import ControlledAdapter, LifecycleBridge, PermissionPolicy
from benchmark_controller.ledger import Ledger


class ExternalAdapterTests(unittest.TestCase):
    def test_permission_modes_fail_closed(self) -> None:
        PermissionPolicy("approve-reads").authorize("read")
        with self.assertRaises(PermissionError):
            PermissionPolicy("approve-reads").authorize("write")
        with self.assertRaises(PermissionError):
            PermissionPolicy("deny-all").authorize("read")

    def test_run_uses_argv_and_redacts_output_from_ledger(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ledger = Ledger(root / "ledger.jsonl", run_id="run_external", task_id="pilot_smoke")
            adapter = ControlledAdapter(root / "workspace", ledger, permission_mode="approve-all")
            result = adapter.run(
                ["python3", "-c", "print('private output')"],
                stage_id="implementation",
                actor="executor",
                access="write",
            )

            self.assertEqual(result.returncode, 0)
            events = [json.loads(line) for line in (root / "ledger.jsonl").read_text().splitlines()]
            self.assertNotIn("private output", json.dumps(events))
            self.assertEqual(events[-1]["event_type"], "adapter.command.executed")
            self.assertEqual(events[-1]["payload_sha256"].__len__(), 64)

    def test_blocked_permission_is_recorded(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ledger = Ledger(root / "ledger.jsonl", run_id="run_blocked", task_id="pilot_smoke")
            adapter = ControlledAdapter(root / "workspace", ledger, permission_mode="approve-reads")
            with self.assertRaises(PermissionError):
                adapter.run(
                    ["python3", "-c", "print('no')"],
                    stage_id="implementation",
                    actor="executor",
                    access="write",
                )
            event = json.loads((root / "ledger.jsonl").read_text().splitlines()[-1])
            self.assertEqual(event["status"], "blocked")

    def test_workspace_boundary_and_lifecycle_event(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ledger = Ledger(root / "ledger.jsonl", run_id="run_boundary", task_id="pilot_smoke")
            adapter = ControlledAdapter(root / "workspace", ledger, permission_mode="approve-all")
            adapter.prepare()
            with self.assertRaises(ValueError):
                adapter.hash_file("../outside")
            event = LifecycleBridge(ledger, tool="compozy").record(
                stage_id="planning", actor="planner", status="completed", event_name="plan.completed"
            )
            self.assertEqual(event["event_type"], "lifecycle.plan.completed")
