import tempfile
import unittest
from pathlib import Path

from benchmark_controller.ledger import Ledger
from benchmark_controller.mini_swe import MiniSweAgentAdapter, MiniSweNotReadyError


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
                ]
            )
            adapter.runtime.run = lambda *args, **kwargs: next(outputs)  # type: ignore[method-assign]
            result = adapter.read_only_preflight()
            self.assertTrue(result.help_probe["passed"])
            self.assertTrue(result.to_dict()["workspace_mounted"])
            self.assertEqual(result.image["image_id"], "sha256:image")

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

    def test_task_execution_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            adapter = MiniSweAgentAdapter(
                root / "workspace",
                Ledger(root / "ledger.jsonl", run_id="run_mini_blocked", task_id="pilot_smoke"),
            )
            with self.assertRaises(MiniSweNotReadyError):
                adapter.run_task(issue_text="pilot")
