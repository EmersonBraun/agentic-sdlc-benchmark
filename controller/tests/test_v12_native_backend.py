from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest

from benchmark_controller.condition_runner import ConditionStep, StepContext
from benchmark_controller.ledger import Ledger
from benchmark_controller.matrix import MatrixAssignment
from benchmark_controller.v12_native_backend import NativeStepExecution, V12NativeStageBackend


class Executor:
    supports_idempotent_replay = True
    enforces_deadline = True

    def __init__(self, *, wrong_workspace=False):
        self.wrong_workspace = wrong_workspace
        self.requests = []

    def execute(self, request):
        self.requests.append(request)
        metadata = {}
        if request.step == "decomposition":
            metadata["handoff_payload"] = {
                "requirements": "resolved", "implementation_plan": ["build"],
                "acceptance_criteria": ["passes"],
            }
        return NativeStepExecution(
            status="completed", role=request.role, provider=request.provider, model=request.model,
            workspace=Path("/tmp/wrong") if self.wrong_workspace else request.worktree,
            effective_work_ms=10, external_wait_ms=2,
            tokens={"input": 1, "output": 2, "cached": 0, "reasoning": 1},
            cost_usd=0.01, metadata=metadata,
        )


class V12NativeBackendTests(unittest.TestCase):
    def context(self, root: Path, step: str):
        worktree = root / "worktree"
        task = worktree / "tasks/public/pilot_greenfield_service_readiness.md"
        task.parent.mkdir(parents=True)
        task.write_text("task")
        assignment = MatrixAssignment(
            1, "run_v12-native", "pilot_greenfield_service_readiness", "greenfield",
            "compozy__off", "compozy", None, "off", 1, 1,
        )
        directory = root / "bundle"
        directory.mkdir()
        bundle = SimpleNamespace(
            ledger=Ledger(directory / "ledger.jsonl", run_id=assignment.run_id, task_id=assignment.task_id),
        )
        return StepContext(
            assignment=assignment, bundle=bundle,
            step=ConditionStep(step, step if step != "local-testing" else "local-testing", "planner" if step == "decomposition" else "executor"),
            attempt=1, worktree=worktree, branch="benchmark/run", idempotency_key=f"{step}-1",
            deadline_epoch_ms=None, accounting_tool=f"accounting-{step}",
        )

    def test_routes_planner_and_executor_to_frozen_models(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            executor = Executor()
            backend = V12NativeStageBackend(executor)
            self.assertEqual(backend.execute_step(self.context(root, "decomposition")).status, "completed")
            self.assertEqual(executor.requests[-1].model, "gpt-5.4")
            self.assertEqual(backend.execute_step(self.context(Path(directory) / "second", "implementation")).status, "completed")
            self.assertEqual(executor.requests[-1].model, "grok-4.5")
            self.assertEqual(backend.execute_step(self.context(Path(directory) / "third", "review")).status, "completed")
            self.assertEqual(
                (executor.requests[-1].role, executor.requests[-1].provider, executor.requests[-1].model),
                ("independent_evaluator", "codex", "gpt-5.4-mini"),
            )

    def test_rejects_native_workspace_escape_and_still_records_accounting(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            context = self.context(root, "implementation")
            result = V12NativeStageBackend(Executor(wrong_workspace=True)).execute_step(context)
            self.assertEqual(result.status, "invalid-measurement")
            events = [line for line in context.bundle.ledger.path.read_text().splitlines() if line]
            self.assertEqual(len(events), 2)
