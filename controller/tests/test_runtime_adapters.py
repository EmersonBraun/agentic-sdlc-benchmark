import json
import tempfile
import unittest
from pathlib import Path

from benchmark_controller.ade_adapters import ADENotReadyError, build_ade_adapter
from benchmark_controller.harness_adapters import HarnessNotReadyError, build_harness_adapter
from benchmark_controller.ledger import Ledger
from benchmark_controller.mini_swe import MiniSweAgentAdapter


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

    def test_openhands_fails_closed_without_session(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ledger = Ledger(root / "ledger.jsonl", run_id="run_harness_blocked", task_id="pilot_smoke")
            harness = build_harness_adapter(
                "openhands-sdk", root / "openhands-sdk", ledger, permission_mode="approve-all"
            )
            with self.assertRaises(HarnessNotReadyError):
                harness.run_command(
                    ["python3", "--version"],
                    stage_id="implementation",
                    actor="executor",
                    access="read",
                )

    def test_mini_swe_registry_resolves_live_cli_bridge(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            harness = build_harness_adapter(
                "mini-swe-agent",
                root / "mini-swe-agent",
                Ledger(root / "ledger.jsonl", run_id="run_mini_registry", task_id="pilot_smoke"),
                permission_mode="approve-all",
            )
            self.assertIsInstance(harness, MiniSweAgentAdapter)
            harness.assert_ready()
            self.assertEqual(
                harness.descriptor.entrypoint,
                "controller:mini-swe-cli-bridge",
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
