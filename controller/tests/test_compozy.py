import json
import tempfile
import unittest
from pathlib import Path

from benchmark_controller.compozy import CompozyAdapter, CompozyNotReadyError
from benchmark_controller.ledger import Ledger


class CompozyAdapterTests(unittest.TestCase):
    def test_read_only_preflight_summarizes_without_raw_config(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            adapter = CompozyAdapter(
                root / "workspace",
                Ledger(root / "ledger.jsonl", run_id="run_compozy", task_id="pilot_smoke"),
            )
            outputs = iter(
                [
                    {"daemon": {"status": "running", "version": "x"}, "health": {"status": "ok"}, "sessions": {"active": 0, "total": 0}},
                    {"status": "ok", "workspace": {"id": "ws", "name": "bench", "root": "/tmp/workspace"}},
                    {"redacted": True, "resolution_source": "cwd", "scope": "workspace", "config": {"permissions": {"mode": "approve-reads"}}},
                    {"data": [], "page": {"has_more": False}},
                    {"providers": [{"auth_status": {"state": "ready"}}, {"auth_status": {"state": "missing_credential"}}]},
                ]
            )
            adapter._json_command = lambda *args, **kwargs: next(outputs)  # type: ignore[method-assign]
            result = adapter.read_only_preflight(workspace_name="bench")
            self.assertEqual(result.status["health_status"], "ok")
            self.assertEqual(result.config["permission_mode"], "approve-reads")
            self.assertEqual(result.providers["states"]["missing_credential"], 1)
            self.assertNotIn("/tmp/workspace", json.dumps(result.to_dict()))

    def test_spawn_fails_closed_before_command_execution(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            adapter = CompozyAdapter(
                root / "workspace",
                Ledger(root / "ledger.jsonl", run_id="run_compozy_blocked", task_id="pilot_smoke"),
            )
            with self.assertRaises(CompozyNotReadyError):
                adapter.spawn()
