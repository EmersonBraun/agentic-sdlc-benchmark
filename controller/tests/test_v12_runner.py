import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest

from benchmark_controller.condition_runner import ConditionStep, StepContext, StepResult
from benchmark_controller.ledger import Ledger
from benchmark_controller.matrix import MatrixAssignment
from benchmark_controller.v12_runner import (
    AGENTSKIT_CONTEXT_RELATIVE,
    HANDOFF_RELATIVE,
    V12HandoffBackend,
    V12NativeConditionRunner,
)


def assignment(factor: str = "on", harness=None) -> MatrixAssignment:
    return MatrixAssignment(
        order=1,
        run_id=f"run_v12-runner-{factor}",
        task_id="pilot_greenfield_service_readiness",
        product_id="greenfield",
        condition_id=f"compozy__{factor}",
        ade="compozy",
        harness=harness,
        agentskit=factor,
        replicate=1,
        randomization_seed=1,
    )


def bundle(root: Path, factor: str = "on"):
    directory = root / "bundle"
    directory.mkdir()
    run_id = f"run_v12-runner-{factor}"
    return SimpleNamespace(
        directory=directory,
        manifest={
            "protocol_version": "v1.2",
            "run_id": run_id,
            "task_id": "pilot_greenfield_service_readiness",
            "task_manifest_sha256": "b" * 64,
            "base_commit": "a" * 40,
        },
        ledger=Ledger(directory / "ledger.jsonl", run_id=run_id, task_id="pilot_greenfield_service_readiness"),
    )


class Delegate:
    supports_idempotent_replay = True
    enforces_deadline = True

    def __init__(self):
        self.contexts = []

    def execute_step(self, context):
        self.contexts.append(context)
        factor_digest = (
            hashlib.sha256(context.agentskit_context_path.read_bytes()).hexdigest()
            if context.agentskit_context_path else None
        )
        if context.step.name == "decomposition":
            return StepResult.completed(metadata={
                "handoff_payload": {
                    "requirements": "A1, A2, A3 resolved",
                    "implementation_plan": ["implement readiness", "test failure mode"],
                    "acceptance_criteria": ["healthy dependency returns ready"],
                },
                "agentskit_context_sha256_observed": factor_digest,
            })
        if context.step.name == "implementation":
            return StepResult.completed(metadata={
                "handoff_sha256_observed": hashlib.sha256(context.handoff_path.read_bytes()).hexdigest(),
                "agentskit_context_sha256_observed": factor_digest,
            })
        return StepResult.completed()


class V12RunnerTests(unittest.TestCase):
    def test_runner_uses_harness_free_v12_state_identity(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            current_bundle = bundle(root)
            runner = object.__new__(V12NativeConditionRunner)
            state = runner._load_or_create_state(
                current_bundle.directory / "condition-runner-state.json",
                assignment(),
                current_bundle,
            )
            self.assertEqual(state["schema_version"], "condition-runner-state-v1.2")
            self.assertEqual(state["factors"], {"ade": "compozy", "agentskit": "on"})
            with self.assertRaisesRegex(RuntimeError, "harness"):
                runner._factors(assignment(harness="reference"))

    def test_materializes_public_factor_and_real_codex_grok_handoff(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            worktree = root / "worktree"
            worktree.mkdir()
            current_bundle = bundle(root)
            delegate = Delegate()
            backend = V12HandoffBackend(
                delegate,
                agentskit_context_factory=lambda context: {
                    "condition_id": context.assignment.condition_id,
                    "task_id": context.assignment.task_id,
                    "public_only": True,
                    "agentskit_os_used": False,
                    "components": ["doc-bridge", "playbook", "code-review"],
                    "guidance": "Use grounded docs, playbook gates, and public code review.",
                },
            )
            base = dict(
                assignment=assignment(), bundle=current_bundle, attempt=1,
                worktree=worktree, branch="benchmark/run", deadline_epoch_ms=None,
                accounting_tool="test-accounting",
            )
            decomposition = backend.execute_step(StepContext(
                step=ConditionStep("decomposition", "decomposition", "planner"),
                idempotency_key="decomposition-1", **base,
            ))
            self.assertEqual(decomposition.status, "completed")
            self.assertTrue((worktree / HANDOFF_RELATIVE).is_file())
            self.assertTrue((worktree / AGENTSKIT_CONTEXT_RELATIVE).is_file())

            implementation = backend.execute_step(StepContext(
                step=ConditionStep("implementation", "implementation", "executor"),
                idempotency_key="implementation-1", **base,
            ))
            self.assertEqual(implementation.status, "completed")
            self.assertIsNotNone(delegate.contexts[-1].handoff_path)

    def test_off_condition_rejects_context_contamination(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            worktree = root / "worktree"
            path = worktree / AGENTSKIT_CONTEXT_RELATIVE
            path.parent.mkdir(parents=True)
            path.write_text("{}")
            current_bundle = bundle(root, "off")
            backend = V12HandoffBackend(Delegate())
            context = StepContext(
                assignment=assignment("off"), bundle=current_bundle,
                step=ConditionStep("requirements", "requirements", "planner"), attempt=1,
                worktree=worktree, branch="benchmark/run", idempotency_key="requirements-1",
                deadline_epoch_ms=None, accounting_tool="test-accounting",
            )
            with self.assertRaisesRegex(RuntimeError, "OFF"):
                backend.execute_step(context)

    def test_tampered_handoff_fails_before_executor(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            worktree = root / "worktree"
            worktree.mkdir()
            current_bundle = bundle(root, "off")
            delegate = Delegate()
            backend = V12HandoffBackend(delegate)
            path = worktree / HANDOFF_RELATIVE
            path.parent.mkdir(parents=True)
            path.write_text(json.dumps({"schema_version": "tampered"}))
            result = backend.execute_step(StepContext(
                assignment=assignment("off"), bundle=current_bundle,
                step=ConditionStep("implementation", "implementation", "executor"), attempt=1,
                worktree=worktree, branch="benchmark/run", idempotency_key="implementation-1",
                deadline_epoch_ms=None, accounting_tool="test-accounting",
            ))
            self.assertEqual(result.status, "invalid-measurement")
            self.assertEqual(delegate.contexts, [])
