import json
import subprocess
import tempfile
import unittest
from dataclasses import dataclass
from pathlib import Path

from benchmark_controller.condition_runner import (
    CONDITION_STEPS,
    ComposedConditionRunner,
    ComposedCollectionBackend,
    GitWorktreeProvider,
    REQUIRED_QUALITY_GATES,
    StepResult,
    WorktreeLease,
)
from benchmark_controller.ledger import Ledger
from benchmark_controller.matrix import MatrixAssignment


@dataclass
class _Bundle:
    directory: Path
    manifest: dict
    ledger: Ledger


class _Worktrees:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.created = 0
        self.released = 0

    def acquire(self, *, run_id: str, base_commit: str) -> WorktreeLease:
        self.created += 1
        path = self.root / run_id
        path.mkdir(parents=True, exist_ok=True)
        return WorktreeLease(path=path, branch=f"benchmark/{run_id}", base_commit=base_commit)

    def release(self, lease: WorktreeLease) -> None:
        self.released += 1


class _Backend:
    supports_idempotent_replay = True
    enforces_deadline = True

    def __init__(self, retry_step: str | None = None) -> None:
        self.calls: list[tuple[str, int]] = []
        self.retry_step = retry_step

    def execute_step(self, context):
        self.calls.append((context.step.name, context.attempt))
        assert context.idempotency_key == f"run_condition-runner:{context.step.name}:{context.attempt}"
        context.bundle.ledger.record(
            stage_id=context.step.stage_id,
            actor=context.step.actor,
            event_type="backend.attempt.effective-work",
            time_category="effective_work",
            duration_ms=1,
            status="completed",
            payload={"attempt": context.attempt},
            tool=context.accounting_tool,
            tokens={"input": 0, "output": 0, "cached": 0, "reasoning": 0},
            cost_usd=0,
        )
        context.bundle.ledger.record(
            stage_id=context.step.stage_id,
            actor=context.step.actor,
            event_type="backend.attempt.external-wait",
            time_category="external_wait",
            duration_ms=0,
            status="completed",
            payload={"attempt": context.attempt},
            tool=context.accounting_tool,
        )
        if context.step.name == self.retry_step and context.attempt == 1:
            return StepResult.retry("transient-provider-error")
        proof = None
        if context.step.name == "documentation":
            proof = {
                "verified_gates": sorted(REQUIRED_QUALITY_GATES - {"merge"}),
                "product_quality_score": 80,
            }
        if context.step.name == "merge":
            proof = {
                "verified_gates": sorted(REQUIRED_QUALITY_GATES),
                "merge_commit": "b" * 40,
                "product_quality_score": 80,
            }
        return StepResult.completed(
            metadata={"native_worktree_mode": context.worktree_mode},
            completion_proof=proof,
        )


class _Verifier:
    enforces_deadline = True

    def verify(self, context, proof):
        return True


def _assignment() -> MatrixAssignment:
    return MatrixAssignment(
        order=1,
        run_id="run_condition-runner",
        task_id="pilot_greenfield_service_readiness",
        product_id="greenfield",
        condition_id="orca__reference__off",
        ade="orca",
        harness="reference",
        agentskit="off",
        replicate=1,
        randomization_seed=10,
    )


class ComposedConditionRunnerTests(unittest.TestCase):
    def _bundle(self, root: Path) -> _Bundle:
        directory = root / "bundle"
        directory.mkdir()
        return _Bundle(
            directory=directory,
            manifest={
                "base_commit": "a" * 40,
                "run_id": "run_condition-runner",
                "task_id": "pilot_greenfield_service_readiness",
                "product_id": "greenfield",
                "condition_id": "orca__reference__off",
                "replicate": 1,
                "randomization_seed": 10,
            },
            ledger=Ledger(directory / "ledger.jsonl", run_id="run_condition-runner", task_id="pilot_greenfield_service_readiness"),
        )

    def test_executes_every_step_with_retry_and_releases_worktree(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            backend = _Backend(retry_step="implementation")
            worktrees = _Worktrees(root / "worktrees")
            runner = ComposedConditionRunner(
                backend, worktrees, _Verifier(), max_attempts=2,
                retry_backoff_seconds=1, sleeper=lambda seconds: None,
            )

            outcome = runner.execute(_assignment(), self._bundle(root))

            self.assertEqual(outcome.terminal_state, "MERGED")
            self.assertEqual(worktrees.created, 1)
            self.assertEqual(worktrees.released, 1)
            self.assertEqual(backend.calls.count(("implementation", 1)), 1)
            self.assertEqual(backend.calls.count(("implementation", 2)), 1)
            state = json.loads((root / "bundle" / "condition-runner-state.json").read_text())
            self.assertEqual(state["terminal_state"], "MERGED")
            self.assertEqual(state["completed_steps"], [step.name for step in CONDITION_STEPS])
            events = [json.loads(line) for line in (root / "bundle" / "ledger.jsonl").read_text().splitlines()]
            self.assertTrue(any(event["event_type"] == "condition.step.retry" for event in events))

    def test_rejects_a_backend_without_idempotent_replay(self) -> None:
        class UnsafeBackend:
            enforces_deadline = True

            def execute_step(self, context):
                return StepResult.completed()

        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, "idempotent replay"):
                ComposedConditionRunner(UnsafeBackend(), _Worktrees(Path(directory)), _Verifier())

    def test_independent_verifier_can_block_merged(self) -> None:
        class RejectingVerifier:
            enforces_deadline = True

            def verify(self, context, proof):
                return False

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            outcome = ComposedConditionRunner(
                _Backend(), _Worktrees(root / "worktrees"), RejectingVerifier()
            ).execute(_assignment(), self._bundle(root))
            self.assertEqual(outcome.terminal_state, "FAILED")
            self.assertEqual(outcome.failure["reason"], "independent-pre-merge-verification-failed")

    def test_official_run_without_frozen_budgets_is_invalid(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bundle = self._bundle(root)
            bundle.manifest.update({"gate_mode": "official-collection", "budgets": {}})
            outcome = ComposedConditionRunner(
                _Backend(), _Worktrees(root / "worktrees"), _Verifier()
            ).execute(_assignment(), bundle)
            self.assertEqual(outcome.terminal_state, "INVALID_MEASUREMENT")
            self.assertEqual(outcome.failure["reason"], "missing-frozen-budgets")

    def test_collection_backend_wires_factories_to_runner(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            worktrees = _Worktrees(root / "worktrees")
            backend = ComposedCollectionBackend(
                worktrees,
                lambda assignment, bundle: _Backend(),
                lambda assignment, bundle: _Verifier(),
                retry_backoff_seconds=1,
            )
            outcome = backend.execute(_assignment(), self._bundle(root))
            self.assertEqual(outcome.terminal_state, "MERGED")
            self.assertEqual(worktrees.created, 1)

    def test_resume_skips_persisted_completed_steps(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bundle = self._bundle(root)
            state = {
                "schema_version": "condition-runner-state-v1.1",
                "run_id": "run_condition-runner",
                "condition_id": "orca__reference__off",
                "factors": {"ade": "orca", "harness": "reference", "agentskit": "off"},
                "worktree": {"path": str(root / "worktrees" / "run_condition-runner"), "branch": "benchmark/run_condition-runner", "base_commit": "a" * 40},
                "completed_steps": ["requirements", "planning"],
                "attempts": {"requirements": 1, "planning": 1},
                "current_step": None,
                "terminal_state": None,
            }
            (bundle.directory / "condition-runner-state.json").write_text(json.dumps(state))
            (root / "worktrees" / "run_condition-runner").mkdir(parents=True)
            backend = _Backend()
            worktrees = _Worktrees(root / "worktrees")

            outcome = ComposedConditionRunner(backend, worktrees, _Verifier()).execute(_assignment(), bundle)

            self.assertEqual(outcome.terminal_state, "INVALID_MEASUREMENT")
            self.assertNotIn(("requirements", 1), backend.calls)
            self.assertNotIn(("planning", 1), backend.calls)
            self.assertEqual(worktrees.created, 0)

    def test_non_retryable_failure_stops_fail_closed_and_preserves_worktree(self) -> None:
        class BrokenBackend(_Backend):
            def execute_step(self, context):
                if context.step.name == "local-testing":
                    super().execute_step(context)
                    return StepResult.failed("tests-failed")
                return super().execute_step(context)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            worktrees = _Worktrees(root / "worktrees")
            outcome = ComposedConditionRunner(BrokenBackend(), worktrees, _Verifier()).execute(
                _assignment(), self._bundle(root)
            )

            self.assertEqual(outcome.terminal_state, "FAILED")
            self.assertEqual(outcome.failure["step"], "local-testing")
            self.assertEqual(worktrees.released, 0)

    def test_human_required_is_a_terminal_measured_outcome(self) -> None:
        class HumanBackend(_Backend):
            def execute_step(self, context):
                if context.step.name == "requirements":
                    super().execute_step(context)
                    return StepResult.human_required("product-decision")
                return super().execute_step(context)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            outcome = ComposedConditionRunner(HumanBackend(), _Worktrees(root / "worktrees"), _Verifier()).execute(
                _assignment(), self._bundle(root)
            )
            self.assertEqual(outcome.terminal_state, "HUMAN_REQUIRED")
            self.assertEqual(outcome.failure["reason"], "product-decision")

    def test_terminal_resume_does_not_execute_or_reacquire(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bundle = self._bundle(root)
            state = {
                "schema_version": "condition-runner-state-v1.1",
                "run_id": "run_condition-runner",
                "condition_id": "orca__reference__off",
                "factors": {"ade": "orca", "harness": "reference", "agentskit": "off"},
                "worktree": None,
                "completed_steps": [],
                "attempts": {},
                "current_step": None,
                "terminal_state": "HUMAN_REQUIRED",
                "failure": {"reason": "credential"},
                "artifacts": [],
            }
            (bundle.directory / "condition-runner-state.json").write_text(json.dumps(state))
            backend = _Backend()
            worktrees = _Worktrees(root / "worktrees")
            outcome = ComposedConditionRunner(backend, worktrees, _Verifier()).execute(_assignment(), bundle)
            self.assertEqual(outcome.terminal_state, "HUMAN_REQUIRED")
            self.assertEqual(worktrees.created, 0)
            self.assertEqual(backend.calls, [])

    def test_resume_replays_an_interrupted_last_attempt_with_same_idempotency_key(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bundle = self._bundle(root)
            worktree = root / "worktrees" / "run_condition-runner"
            worktree.mkdir(parents=True)
            state = {
                "schema_version": "condition-runner-state-v1.1",
                "run_id": "run_condition-runner",
                "condition_id": "orca__reference__off",
                "factors": {"ade": "orca", "harness": "reference", "agentskit": "off"},
                "worktree": {"path": str(worktree), "branch": "benchmark/run_condition-runner", "base_commit": "a" * 40},
                "worktree_event_recorded": True,
                "completed_steps": [step.name for step in CONDITION_STEPS[:3]],
                "attempts": {"implementation": 3},
                "current_step": "implementation",
                "terminal_state": None,
                "failure": None,
                "artifacts": [],
            }
            (bundle.directory / "condition-runner-state.json").write_text(json.dumps(state))
            backend = _Backend()
            outcome = ComposedConditionRunner(backend, _Worktrees(root / "worktrees"), _Verifier(), max_attempts=3).execute(
                _assignment(), bundle
            )
            self.assertEqual(outcome.terminal_state, "INVALID_MEASUREMENT")
            self.assertEqual(backend.calls, [])

    def test_resume_finishes_idempotent_cleanup_after_worktree_was_removed(self) -> None:
        class IdempotentWorktrees(_Worktrees):
            def release(self, lease: WorktreeLease) -> None:
                self.released += 1

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bundle = self._bundle(root)
            state = {
                "schema_version": "condition-runner-state-v1.1",
                "run_id": "run_condition-runner",
                "condition_id": "orca__reference__off",
                "factors": {"ade": "orca", "harness": "reference", "agentskit": "off"},
                "worktree": {"path": str(root / "missing"), "branch": "benchmark/run_condition-runner", "base_commit": "a" * 40},
                "completed_steps": [step.name for step in CONDITION_STEPS],
                "attempts": {},
                "current_step": None,
                "terminal_state": "MERGED",
                "failure": None,
                "cleanup_pending": True,
                "worktree_release_event_recorded": False,
                "artifacts": [],
            }
            (bundle.directory / "condition-runner-state.json").write_text(json.dumps(state))
            worktrees = IdempotentWorktrees(root / "worktrees")
            outcome = ComposedConditionRunner(_Backend(), worktrees, _Verifier()).execute(_assignment(), bundle)
            self.assertEqual(outcome.terminal_state, "MERGED")
            self.assertEqual(worktrees.released, 1)
            persisted = json.loads((bundle.directory / "condition-runner-state.json").read_text())
            self.assertFalse(persisted["cleanup_pending"])


class GitWorktreeProviderTests(unittest.TestCase):
    def test_creates_and_removes_an_isolated_branch(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repository = root / "repository"
            repository.mkdir()
            subprocess.run(["git", "init", "-q"], cwd=repository, check=True)
            subprocess.run(["git", "config", "user.email", "benchmark@example.invalid"], cwd=repository, check=True)
            subprocess.run(["git", "config", "user.name", "Benchmark"], cwd=repository, check=True)
            (repository / "README.md").write_text("fixture\n")
            subprocess.run(["git", "add", "README.md"], cwd=repository, check=True)
            subprocess.run(["git", "commit", "-qm", "fixture"], cwd=repository, check=True)
            commit = subprocess.run(
                ["git", "rev-parse", "HEAD"], cwd=repository, check=True, capture_output=True, text=True
            ).stdout.strip()
            provider = GitWorktreeProvider(repository, root / "worktrees")
            lease = provider.acquire(run_id="run_fixture", base_commit=commit)
            self.assertTrue((lease.path / "README.md").is_file())
            self.assertEqual(lease.branch, "benchmark/run_fixture")
            provider.release(lease)
            self.assertFalse(lease.path.exists())


if __name__ == "__main__":
    unittest.main()
