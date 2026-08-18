import json
import sys
import tempfile
import unittest
from pathlib import Path

from benchmark_controller.agent_orchestrator import AgentOrchestratorAdapter
from benchmark_controller.ledger import Ledger


class AgentOrchestratorAdapterTests(unittest.TestCase):
    def _adapter(self, root: Path, *, permission_mode: str = "approve-reads") -> AgentOrchestratorAdapter:
        return AgentOrchestratorAdapter(
            root / "workspace",
            Ledger(root / "ledger.jsonl", run_id="run_ao", task_id="pilot_smoke"),
            cli_path=sys.executable,
            permission_mode=permission_mode,
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

    def test_spawn_still_requires_explicit_write_permission(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            adapter = self._adapter(root)
            with self.assertRaises(PermissionError):
                adapter.spawn(project_id="code-10x", name="pilot", issue="pilot-1", prompt="run")
            events = (root / "ledger.jsonl").read_text(encoding="utf-8")
            self.assertIn("adapter.command.blocked", events)

    def test_collection_path_observes_and_terminates_session(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            adapter = self._adapter(root, permission_mode="approve-all")
            snapshots = iter(
                [
                    {"session": {"id": "session-1", "status": "working"}},
                    {"session": {"id": "session-1", "status": "terminated"}},
                ]
            )
            adapter._json_command = lambda *args, **kwargs: next(snapshots)
            adapter.runtime.run = lambda *args, **kwargs: type("Result", (), {"returncode": 0})()
            snapshot = adapter.observe_session(project_id="code-10x", session_id="session-1")
            adapter.terminate_session(project_id="code-10x", session_id="session-1")
            self.assertEqual(snapshot["session"]["status"], "working")
            events = (root / "ledger.jsonl").read_text(encoding="utf-8")
            self.assertIn("session.state", events)

    def test_termination_fails_closed_without_observed_terminal_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            adapter = self._adapter(root, permission_mode="approve-all")
            adapter._json_command = lambda *args, **kwargs: {
                "session": {"id": "session-1", "status": "working"}
            }
            adapter.runtime.run = lambda *args, **kwargs: type("Result", (), {"returncode": 0})()
            with self.assertRaisesRegex(RuntimeError, "not independently observed"):
                adapter.terminate_session(
                    project_id="code-10x", session_id="session-1", timeout_seconds=0.01
                )
