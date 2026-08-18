import json
import hashlib
import tempfile
import unittest
from pathlib import Path

from benchmark_controller.orca import OrcaAdapter
from benchmark_controller.ledger import Ledger
from benchmark_controller.external import AdapterCommandResult


class OrcaAdapterTests(unittest.TestCase):
    def test_v11_passing_attestation_is_ledger_and_source_bound(self) -> None:
        root = Path(__file__).resolve().parents[2]
        attestation = json.loads((root / "adapters/orca-v1.1-lifecycle-probe-attestation-5.json").read_text())
        self.assertEqual(attestation["status"], "passed")
        self.assertTrue(attestation["orchestration"]["worker_done_accepted"])
        self.assertEqual(attestation["orchestration"]["dispatch_terminal_state"], "completed")
        self.assertEqual(attestation["cleanup"]["live_probe_terminals_remaining"], 0)
        evidence = attestation["evidence"]
        for field, path in (
            ("ledger_sha256", root / "adapters/orca-v1.1-lifecycle-probe-ledger-5.jsonl"),
            ("orca_adapter_source_sha256", root / "controller/src/benchmark_controller/orca.py"),
            ("ade_registry_source_sha256", root / "controller/src/benchmark_controller/ade_adapters.py"),
            ("descriptor_source_sha256", root / "controller/src/benchmark_controller/adapters.py"),
            ("probe_source_sha256", root / "controller/scripts/probe_orca_lifecycle.py"),
            ("observation_sha256", root / "adapters/orca-v1.1-lifecycle-observation-5.json"),
        ):
            self.assertEqual(evidence[field], hashlib.sha256(path.read_bytes()).hexdigest())

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
                    {"ok": True, "result": {"worktrees": [{"path": "/some/other/worktree"}]}},
                    {"ok": True, "result": {"claude": {"accounts": []}, "codex": {"accounts": [], "systemDefault": {"hasAuth": True}}, "rateLimits": {"codex": {"status": "ok"}}}},
                ]
            )
            adapter._json_command = lambda *args, **kwargs: next(outputs)  # type: ignore[method-assign]
            result = adapter.read_only_preflight()
            self.assertEqual(result.status["graph_state"], "unavailable")
            self.assertTrue(result.agent_context["machine_readable"])
            self.assertEqual(result.worktree["error_code"], "selector_not_found")
            self.assertFalse(result.worktree_catalog["benchmark_workspace_registered"])
            self.assertEqual(result.worktree_catalog["count"], 1)
            self.assertTrue(result.accounts["system_default_auth"])
            self.assertNotIn("private", json.dumps(result.to_dict()))

    def test_ready_workflow_binds_coordinator_identity(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            adapter = OrcaAdapter(
                root / "workspace",
                Ledger(root / "ledger.jsonl", run_id="run_orca_blocked", task_id="pilot_smoke"),
            )
            observed = {}
            adapter._json_command = lambda args, **kwargs: observed.update(args=args, kwargs=kwargs) or {"ok": True, "result": {"run": {"id": "run_bound"}}}  # type: ignore[method-assign]
            adapter.start_workflow(objective="pilot", coordinator_handle="term_coordinator")
            self.assertIn("term_coordinator", observed["args"])
            self.assertEqual(observed["kwargs"]["access"], "write")

    def test_ready_dispatch_enforces_create_wait_inject_order(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            adapter = OrcaAdapter(
                root / "workspace",
                Ledger(root / "ledger.jsonl", run_id="run_orca_sequence", task_id="pilot_smoke"),
                permission_mode="approve-all",
            )
            adapter.run_id = "run_bound"
            adapter.coordinator_handle = "term_coordinator"
            commands = []
            outputs = iter([
                {"ok": True, "result": {"worktree": {"id": "repo::workspace", "path": str((root / "workspace").resolve())}}},
                {"ok": True, "result": {"terminal": {"handle": "term_worker"}}},
                {"ok": True, "result": {"wait": {"satisfied": True, "status": "running"}}},
                {"ok": True, "result": {"dispatch": {"id": "ctx_ready"}}},
            ])
            adapter._json_command = lambda args, **kwargs: commands.append(args) or next(outputs)  # type: ignore[method-assign]
            result = adapter.start_ready_dispatch(
                task_id="task_ready", coordinator_handle="term_coordinator", agent_command="codex",
            )
            self.assertEqual(result["terminal_handle"], "term_worker")
            self.assertEqual([command[:2] for command in commands], [("worktree", "current"), ("terminal", "create"), ("terminal", "wait"), ("orchestration", "dispatch")])
            self.assertIn("id:repo::workspace", commands[1])
            self.assertIn("tui-idle", commands[2])
            self.assertIn("--inject", commands[3])

    def test_json_command_rejects_semantic_cli_failure(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            adapter = OrcaAdapter(
                root / "workspace",
                Ledger(root / "ledger.jsonl", run_id="run_orca_error", task_id="pilot_smoke"),
            )
            adapter.runtime.run = lambda *args, **kwargs: AdapterCommandResult(("orca",), 0, json.dumps({"ok": False, "error": {"code": "failed"}}), "")  # type: ignore[method-assign]
            with self.assertRaisesRegex(RuntimeError, "ORCA command failed"):
                adapter._json_command(("status", "--json"), stage_id="intake")
