import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from benchmark_controller.orca_v12_executor import OrcaCommandResult, OrcaV12RoleExecutor
from benchmark_controller.v12_native_backend import NativeStepRequest


class Transport:
    def __init__(self, run_id: str, step: str):
        self.run_id = run_id
        self.step = step
        self.calls = []

    def run_json(self, argv, *, timeout_seconds):
        self.calls.append(tuple(argv))
        if argv[0] == "status":
            value = {"ok": True, "result": {
                "runtime": {"state": "ready", "appVersion": "1.4.184"},
                "graph": {"state": "ready"},
            }}
        elif argv[:2] == ("terminal", "create"):
            handle = "term_coordinator" if "zsh" in argv else "term_worker"
            value = {"ok": True, "result": {"terminal": {"handle": handle}}}
        elif argv[:2] == ("orchestration", "run-create"):
            value = {"ok": True, "result": {"run": {"id": "orca_run"}}}
        elif argv[:2] == ("orchestration", "task-create"):
            value = {"ok": True, "result": {"task": {"id": "task_stage"}}}
        elif argv[:2] == ("terminal", "wait"):
            value = {"ok": True, "result": {"wait": {"satisfied": True, "status": "running"}}}
        elif argv[:2] == ("orchestration", "dispatch"):
            value = {"ok": True, "result": {"dispatch": {"id": "dispatch_stage"}}}
        elif argv[:2] == ("orchestration", "dispatch-show"):
            value = {"ok": True, "result": {"dispatch": {
                "id": "dispatch_stage", "status": "completed", "failure_count": 0,
                "capability_hash": "cap", "capability_revoked_at": "now",
            }}}
        elif argv[:2] == ("orchestration", "check") and "--ack" not in argv:
            value = {"ok": True, "result": {
                "deliveryId": "delivery", "messages": [{
                    "type": "worker_done", "payload": json.dumps({
                        "taskId": "task_stage", "dispatchId": "dispatch_stage", "outcome": "succeeded",
                    }),
                }],
            }}
        elif argv[:2] == ("terminal", "read"):
            sentinel = "V12_ORCA_" + hashlib.sha256(
                f"{self.run_id}:{self.step}".encode()
            ).hexdigest()[:20].upper()
            payload = json.dumps({"handoff_payload": {
                "requirements": "resolved", "implementation_plan": ["build"],
                "acceptance_criteria": ["passes"],
            }})
            value = {"ok": True, "result": {"terminal": {
                "tail": ["gpt-5.4", payload, sentinel],
            }}}
        elif argv[:2] == ("terminal", "show"):
            value = {"ok": True, "result": {"terminal": {"connected": False}}}
        else:
            value = {"ok": True, "result": {}}
        return OrcaCommandResult(value, 1)


class OrcaV12ExecutorTests(unittest.TestCase):
    def request(self, root: Path) -> NativeStepRequest:
        task = root / "tasks/public/pilot_greenfield_service_readiness.md"
        task.parent.mkdir(parents=True)
        task.write_text("task")
        return NativeStepRequest(
            run_id="run_orca-test", condition_id="orca__off",
            task_id="pilot_greenfield_service_readiness", step="decomposition",
            role="planner_requirements_lead", provider="codex-cli", model="gpt-5.4",
            worktree=root, branch="benchmark/run_orca-test",
            idempotency_key="run_orca-test:decomposition:1", deadline_epoch_ms=None,
            task_path=task, handoff_path=None, agentskit_context_path=None,
        )

    def test_runs_capability_bound_dispatch_and_extracts_handoff(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            transport = Transport("run_orca-test", "decomposition")
            executor = OrcaV12RoleExecutor(transport=transport, stable_idle_seconds=0)
            result = executor.execute(self.request(root))
            self.assertEqual(result.status, "completed")
            self.assertEqual(result.metadata["handoff_payload"]["requirements"], "resolved")
            self.assertFalse(result.token_cost_accounting_observed)
            self.assertTrue(any(call[:2] == ("orchestration", "dispatch") for call in transport.calls))
            self.assertTrue(any("--ack" in call for call in transport.calls))
            executor.close()

    def test_completed_stage_is_semantically_cached(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            transport = Transport("run_orca-test", "decomposition")
            executor = OrcaV12RoleExecutor(transport=transport, stable_idle_seconds=0)
            request = self.request(root)
            first = executor.execute(request)
            second = executor.execute(request.__class__(**{
                **request.__dict__, "idempotency_key": "run_orca-test:decomposition:2",
            }))
            self.assertIs(first, second)
            self.assertEqual(sum(call[:2] == ("orchestration", "dispatch") for call in transport.calls), 1)

    def test_expired_deadline_has_no_side_effects(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            transport = Transport("run_orca-test", "decomposition")
            request = self.request(root)
            request = request.__class__(**{**request.__dict__, "deadline_epoch_ms": 1})
            result = OrcaV12RoleExecutor(transport=transport, stable_idle_seconds=0).execute(request)
            self.assertEqual(result.status, "timeout")
            self.assertEqual(transport.calls, [])

    def test_close_propagates_to_evaluator(self):
        class Evaluator:
            closed = False

            def close(self):
                self.closed = True

        evaluator = Evaluator()
        OrcaV12RoleExecutor(
            transport=Transport("run", "x"), evaluator=evaluator, stable_idle_seconds=0,
        ).close()
        self.assertTrue(evaluator.closed)
