import json
import sys
import tempfile
import unittest
from pathlib import Path

from benchmark_controller.agent_orchestrator import (
    AgentOrchestratorAdapter,
    AgentOrchestratorNotReadyError,
)
from benchmark_controller.ledger import Ledger


class AgentOrchestratorAdapterTests(unittest.TestCase):
    def _adapter(self, root: Path) -> AgentOrchestratorAdapter:
        return AgentOrchestratorAdapter(
            root / "workspace",
            Ledger(root / "ledger.jsonl", run_id="run_ao", task_id="pilot_smoke"),
            cli_path=sys.executable,
        )

    def test_read_only_preflight_uses_json_commands_without_spawning(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            adapter = self._adapter(root)
            payload = json.dumps({"status": "ok"})
            # The fake CLI returns one JSON object for every read-only command.
            adapter.runtime.run = lambda command, **kwargs: type(
                "Result", (), {"returncode": 0, "stdout": payload, "stderr": "", "timed_out": False}
            )()
            result = adapter.read_only_preflight(project_id="code-10x")
            self.assertEqual(result.daemon, {"status": "ok"})
            self.assertEqual(result.agents["auth_probe"], "passed")
            self.assertFalse(result.to_dict()["agent_sessions_started"])

    def test_spawn_fails_closed_before_command_execution(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            adapter = self._adapter(root)
            with self.assertRaises(AgentOrchestratorNotReadyError):
                adapter.spawn(project_id="code-10x", name="pilot", issue="pilot-1", prompt="run")
            events = (root / "ledger.jsonl").read_text(encoding="utf-8")
            self.assertIn("lifecycle.session.spawn", events)
