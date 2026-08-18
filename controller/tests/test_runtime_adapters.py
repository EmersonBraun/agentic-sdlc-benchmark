import json
import tempfile
import unittest
from pathlib import Path
from subprocess import CompletedProcess
from unittest.mock import patch

from benchmark_controller.ade_adapters import ADENotReadyError, build_ade_adapter
from benchmark_controller.harness_adapters import build_harness_adapter
from benchmark_controller.ledger import Ledger
from benchmark_controller.mini_swe import MiniSweAgentAdapter
from benchmark_controller.openhands_sdk import OpenHandsSDKAdapter, RUNTIME_IMAGE, _replace_workspace


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

    def test_openhands_resolves_ready_pinned_container_bridge(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ledger = Ledger(root / "ledger.jsonl", run_id="run_harness_blocked", task_id="pilot_smoke")
            harness = build_harness_adapter(
                "openhands-sdk", root / "openhands-sdk", ledger, permission_mode="approve-all"
            )
            harness.assert_ready()
            self.assertIsInstance(harness, OpenHandsSDKAdapter)
            self.assertEqual(harness.descriptor.adapter_version, "openhands-sdk-1.42.1")

    def test_openhands_executes_through_container_and_records_cleanup(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ledger = Ledger(root / "ledger.jsonl", run_id="run_openhands_mock", task_id="pilot_smoke")
            harness = build_harness_adapter("openhands-sdk", root / "workspace", ledger, permission_mode="approve-all")

            def fake_run(command, **kwargs):
                argv = tuple(command)
                if argv[:3] == ("docker", "container", "inspect"):
                    return CompletedProcess(argv, 1, "", "Error: No such object")
                if argv[:3] == ("docker", "image", "inspect"):
                    if RUNTIME_IMAGE in argv:
                        return CompletedProcess(argv, 0, "sha256:test", "")
                    return CompletedProcess(argv, 1, "", "Error: No such image")
                if argv[:2] == ("docker", "start"):
                    payload = {"schema_version": "openhands-command-result-v1.1", "returncode": 0, "stdout": "ok\n", "stderr": ""}
                    return CompletedProcess(argv, 0, json.dumps(payload) + "\n", "")
                return CompletedProcess(argv, 0, "", "")

            with patch("benchmark_controller.openhands_sdk.subprocess.run", side_effect=fake_run):
                result = harness.run_command(["git", "status", "--short"], stage_id="local-testing", actor="executor", access="read")
            self.assertEqual(result.stdout, "ok\n")
            event = json.loads(ledger.path.read_text().splitlines()[-1])
            self.assertEqual(event["status"], "completed")

    def test_openhands_writeback_preserves_git_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target, source = root / "target", root / "source"
            (target / ".git").mkdir(parents=True)
            (target / ".git/HEAD").write_text("old")
            (source / ".git").mkdir(parents=True)
            (source / ".git/HEAD").write_text("new")
            (source / "result.txt").write_text("done")
            _replace_workspace(target, source)
            self.assertEqual((target / ".git/HEAD").read_text(), "new")
            self.assertEqual((target / "result.txt").read_text(), "done")

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
