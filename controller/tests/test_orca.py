import json
import tempfile
import unittest
from pathlib import Path

from benchmark_controller.orca import OrcaAdapter, OrcaNotReadyError
from benchmark_controller.ledger import Ledger


class OrcaAdapterTests(unittest.TestCase):
    def test_read_only_preflight_redacts_runtime_details(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            adapter = OrcaAdapter(
                root / "workspace",
                Ledger(root / "ledger.jsonl", run_id="run_orca", task_id="pilot_smoke"),
            )
            outputs = iter(
                [
                    {"ok": True, "result": {"app": {"running": True}, "runtime": {"reachable": True, "state": "graph_not_ready", "appVersion": "x", "runtimeId": "private", "capabilities": ["a"]}, "graph": {"state": "unavailable"}}},
                    {"ok": True, "result": {"schemaVersion": "v1", "commands": [{"name": "status"}]}},
                    {"ok": False, "error": {"code": "selector_not_found"}},
                ]
            )
            adapter._json_command = lambda *args, **kwargs: next(outputs)  # type: ignore[method-assign]
            result = adapter.read_only_preflight()
            self.assertEqual(result.status["graph_state"], "unavailable")
            self.assertTrue(result.agent_context["machine_readable"])
            self.assertEqual(result.worktree["error_code"], "selector_not_found")
            self.assertNotIn("private", json.dumps(result.to_dict()))

    def test_workflow_creation_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            adapter = OrcaAdapter(
                root / "workspace",
                Ledger(root / "ledger.jsonl", run_id="run_orca_blocked", task_id="pilot_smoke"),
            )
            with self.assertRaises(OrcaNotReadyError):
                adapter.start_workflow(objective="pilot")
