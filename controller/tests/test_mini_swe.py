import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from benchmark_controller.ledger import Ledger
from benchmark_controller.mini_swe import MiniSweAgentAdapter, _last_json_object


class MiniSweAdapterTests(unittest.TestCase):
    def test_container_command_is_isolated(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            adapter = MiniSweAgentAdapter(
                root / "workspace",
                Ledger(root / "ledger.jsonl", run_id="run_mini", task_id="pilot_smoke"),
            )
            command = adapter._container_command("--help")
            self.assertIn("none", command)
            self.assertIn("--read-only", command)
            self.assertIn("HOME=/tmp", command)
            self.assertNotIn(str(root / "workspace"), command)

    def test_preflight_summary_contract(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            adapter = MiniSweAgentAdapter(
                root / "workspace",
                Ledger(root / "ledger.jsonl", run_id="run_mini", task_id="pilot_smoke"),
            )
            outputs = iter(
                [
                    type("Result", (), {"returncode": 0, "stdout": "sha256:image\n", "stderr": ""})(),
                    type("Result", (), {"returncode": 0, "stdout": "This is mini-swe-agent version 2.4.6\n", "stderr": ""})(),
                    type("Result", (), {"returncode": 0, "stdout": "mini-swe workspace boundary ok\n", "stderr": ""})(),
                    type("Result", (), {"returncode": 1, "stdout": "Aborted.\n", "stderr": ""})(),
                ]
            )
            adapter.runtime.run = lambda *args, **kwargs: next(outputs)  # type: ignore[method-assign]
            result = adapter.read_only_preflight()
            self.assertTrue(result.help_probe["passed"])
            self.assertTrue(result.to_dict()["workspace_mounted"])
            self.assertEqual(result.image["image_id"], "sha256:image")
            self.assertTrue(result.model_probe["fail_closed"])

    def test_workspace_probe_mounts_read_only_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            adapter = MiniSweAgentAdapter(
                root / "workspace",
                Ledger(root / "ledger.jsonl", run_id="run_mini_mount", task_id="pilot_smoke"),
            )
            command = adapter._workspace_probe_command()
            self.assertIn("type=bind", " ".join(command))
            self.assertIn("dst=/workspace,readonly", " ".join(command))
            self.assertIn("BENCHMARK_PERMISSION_MODE", " ".join(command))

    def test_task_execution_requires_explicit_write_and_network_permission(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            adapter = MiniSweAgentAdapter(
                root / "workspace",
                Ledger(root / "ledger.jsonl", run_id="run_mini_blocked", task_id="pilot_smoke"),
            )
            with self.assertRaises(PermissionError):
                adapter.run_task(issue_text="pilot")

    def test_ready_task_uses_cli_runner_and_redacted_summary(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            adapter = MiniSweAgentAdapter(
                root / "workspace",
                Ledger(root / "ledger.jsonl", run_id="run_mini_live", task_id="pilot_mini_live"),
                permission_mode="approve-all",
            )
            adapter.descriptor = replace(adapter.descriptor, implementation_status="installed-ready")
            captured = {}

            def run(command, **kwargs):
                captured["command"] = command
                captured["kwargs"] = kwargs
                return type(
                    "Result",
                    (),
                    {
                        "returncode": 0,
                        "stdout": 'runner banner\n{"status":"passed","mode":"task-execution"}\n',
                        "stderr": "",
                    },
                )()

            adapter.runtime.run = run  # type: ignore[method-assign]
            summary = adapter.run_task(issue_text="Implement the bounded task")

            self.assertEqual(summary["mode"], "task-execution")
            self.assertEqual(captured["kwargs"]["access"], "network")
            self.assertEqual(captured["kwargs"]["time_category"], "harness_overhead")
            self.assertIn("--workspace", captured["command"])
            task_path = Path(captured["command"][captured["command"].index("--task-file") + 1])
            self.assertFalse(task_path.exists())

    def test_extracts_last_json_summary_after_runner_banner(self) -> None:
        self.assertEqual(
            _last_json_object('notice {not-json}\n{"status":"passed"}\n'),
            {"status": "passed"},
        )
