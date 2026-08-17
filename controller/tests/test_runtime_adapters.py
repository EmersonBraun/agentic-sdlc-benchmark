import json
import tempfile
import unittest
from pathlib import Path

from benchmark_controller.ade_adapters import ADENotReadyError, build_ade_adapter
from benchmark_controller.harness_adapters import HarnessNotReadyError, build_harness_adapter
from benchmark_controller.ledger import Ledger


class RuntimeAdapterRegistryTests(unittest.TestCase):
    def test_reference_harness_uses_shared_boundary(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ledger = Ledger(root / "ledger.jsonl", run_id="run_reference", task_id="pilot_smoke")
            harness = build_harness_adapter(
                "reference", root / "workspace", ledger, permission_mode="approve-all"
            )
            result = harness.run_command(
                ["python3", "-c", "print('ok')"],
                stage_id="local-testing",
                actor="executor",
                access="write",
            )
            self.assertEqual(result.stdout.strip(), "ok")

    def test_external_harnesses_fail_closed_without_sessions(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ledger = Ledger(root / "ledger.jsonl", run_id="run_harness_blocked", task_id="pilot_smoke")
            for key in ("openhands-sdk", "mini-swe-agent"):
                harness = build_harness_adapter(
                    key, root / key, ledger, permission_mode="approve-all"
                )
                with self.assertRaises(HarnessNotReadyError):
                    harness.run_command(
                        ["python3", "--version"],
                        stage_id="implementation",
                        actor="executor",
                        access="read",
                    )

    def test_ade_not_ready_attempt_is_ledger_visible(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ledger = Ledger(root / "ledger.jsonl", run_id="run_ade_blocked", task_id="pilot_smoke")
            ade = build_ade_adapter("compozy", root / "workspace", ledger, permission_mode="approve-reads")
            with self.assertRaises(ADENotReadyError):
                ade.record_lifecycle(stage_id="planning", actor="planner", status="started")
            ade.record_blocked_attempt(stage_id="planning", actor="planner")
            event = json.loads((root / "ledger.jsonl").read_text().splitlines()[-1])
            self.assertEqual(event["status"], "blocked")
            self.assertEqual(event["tool"], "compozy")

    def test_unknown_adapter_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ledger = Ledger(root / "ledger.jsonl", run_id="run_unknown", task_id="pilot_smoke")
            with self.assertRaisesRegex(ValueError, "Unknown ADE"):
                build_ade_adapter("unknown", root / "workspace", ledger, permission_mode="deny-all")
