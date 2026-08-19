import json
from pathlib import Path
import tempfile
import unittest

from benchmark_controller.codex_evaluator_v12 import (
    CodexCommandResult,
    CodexEvaluatorV12RoleExecutor,
    CodexV12CompletionVerifier,
    EXTERNAL_ONLY_GATES,
    RUBRIC_WEIGHTS,
)
from benchmark_controller.condition_runner import PRE_MERGE_QUALITY_GATES, ConditionStep, StepContext
from benchmark_controller.ledger import Ledger
from benchmark_controller.matrix import MatrixAssignment
from benchmark_controller.v12_native_backend import NativeStepRequest


class Transport:
    def __init__(self):
        self.calls = []

    def run(self, argv, *, timeout_seconds):
        self.calls.append((tuple(argv), timeout_seconds))
        proof = {
            "completion_proof": {
                "verified_gates": sorted(PRE_MERGE_QUALITY_GATES - EXTERNAL_ONLY_GATES),
                "product_quality_score": 91,
                "scores": {name: 91 for name in RUBRIC_WEIGHTS},
            }
        }
        events = [
            {"type": "thread.started", "thread_id": "thread"},
            {"type": "item.completed", "item": {
                "type": "agent_message", "text": json.dumps(proof),
            }},
            {"type": "turn.completed", "usage": {
                "input_tokens": 12, "output_tokens": 8,
                "cached_input_tokens": 4, "reasoning_output_tokens": 2,
            }},
        ]
        return CodexCommandResult("\n".join(json.dumps(event) for event in events), 25)


class CodexEvaluatorV12Tests(unittest.TestCase):
    def request(self, root: Path, **overrides):
        values = dict(
            run_id="run_eval", condition_id="orca__off", task_id="pilot_task",
            step="review", role="independent_evaluator", provider="codex",
            model="gpt-5.4-mini", worktree=root, branch="benchmark/run_eval",
            idempotency_key="run_eval:review:1", deadline_epoch_ms=None,
            task_path=root / "task.md", handoff_path=None,
            agentskit_context_path=None,
        )
        values.update(overrides)
        return NativeStepRequest(**values)

    def test_runs_pinned_read_only_ephemeral_codex_and_parses_proof(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            transport = Transport()
            result = CodexEvaluatorV12RoleExecutor(transport).execute(self.request(root))
            self.assertEqual(result.status, "completed")
            self.assertEqual(result.completion_proof["product_quality_score"], 91)
            self.assertEqual(result.tokens, {"input": 12, "output": 8, "cached": 4, "reasoning": 2})
            self.assertFalse(result.token_cost_accounting_observed)
            self.assertTrue(result.metadata["usage_observation"]["token_breakdown_observed"])
            self.assertFalse(result.metadata["usage_observation"]["cost_observed"])
            argv = transport.calls[0][0]
            self.assertIn(("-m", "gpt-5.4-mini"), tuple(zip(argv, argv[1:])))
            self.assertIn(("-s", "read-only"), tuple(zip(argv, argv[1:])))
            self.assertIn("--ephemeral", argv)
            self.assertIn("--ignore-user-config", argv)
            for feature in ("plugins", "remote_plugin", "skill_search", "apps", "multi_agent"):
                self.assertIn(feature, argv)

    def test_wrong_role_binding_fails_before_launch(self):
        with tempfile.TemporaryDirectory() as directory:
            transport = Transport()
            request = self.request(Path(directory), model="gpt-5.4")
            result = CodexEvaluatorV12RoleExecutor(transport).execute(request)
            self.assertEqual(result.status, "failed")
            self.assertEqual(transport.calls, [])

    def test_expired_deadline_has_no_side_effects(self):
        with tempfile.TemporaryDirectory() as directory:
            transport = Transport()
            request = self.request(Path(directory), deadline_epoch_ms=1)
            result = CodexEvaluatorV12RoleExecutor(transport).execute(request)
            self.assertEqual(result.status, "timeout")
            self.assertEqual(transport.calls, [])

    def test_ambiguous_final_messages_fail_closed(self):
        class Ambiguous(Transport):
            def run(self, argv, *, timeout_seconds):
                result = super().run(argv, timeout_seconds=timeout_seconds)
                return CodexCommandResult(result.stdout + "\n" + result.stdout.splitlines()[1], 25)

        with tempfile.TemporaryDirectory() as directory:
            result = CodexEvaluatorV12RoleExecutor(Ambiguous()).execute(self.request(Path(directory)))
            self.assertEqual(result.status, "failed")
            self.assertEqual(result.reason, "invalid-evaluator-output")

    def test_markdown_fenced_json_is_accepted_as_one_structured_proof(self):
        class Fenced(Transport):
            def run(self, argv, *, timeout_seconds):
                result = super().run(argv, timeout_seconds=timeout_seconds)
                events = [json.loads(line) for line in result.stdout.splitlines()]
                events[1]["item"]["text"] = "```json\n" + events[1]["item"]["text"] + "\n```"
                return CodexCommandResult("\n".join(json.dumps(event) for event in events), 25)

        with tempfile.TemporaryDirectory() as directory:
            result = CodexEvaluatorV12RoleExecutor(Fenced()).execute(self.request(Path(directory)))
            self.assertEqual(result.status, "completed")

    def test_distinct_verification_idempotency_keys_force_fresh_evaluations(self):
        with tempfile.TemporaryDirectory() as directory:
            transport = Transport()
            executor = CodexEvaluatorV12RoleExecutor(transport)
            root = Path(directory)
            executor.execute(self.request(root, idempotency_key="run_eval:review:1"))
            executor.execute(self.request(root, idempotency_key="run_eval:pre-merge-verification"))
            self.assertEqual(len(transport.calls), 2)

    def test_turn_failure_after_message_is_rejected(self):
        class FailedTurn(Transport):
            def run(self, argv, *, timeout_seconds):
                result = super().run(argv, timeout_seconds=timeout_seconds)
                return CodexCommandResult(
                    result.stdout + "\n" + json.dumps({"type": "turn.failed", "error": {}}), 25,
                )

        with tempfile.TemporaryDirectory() as directory:
            result = CodexEvaluatorV12RoleExecutor(FailedTurn()).execute(self.request(Path(directory)))
            self.assertEqual(result.status, "failed")

    def test_completion_verifier_fails_closed_without_external_gate_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            task = root / "tasks/public/pilot_task.md"
            task.parent.mkdir(parents=True)
            task.write_text("task")
            bundle_dir = root / "bundle"
            bundle_dir.mkdir()
            bundle = type("Bundle", (), {
                "ledger": Ledger(bundle_dir / "ledger.jsonl", run_id="run_eval", task_id="pilot_task"),
            })()
            assignment = MatrixAssignment(
                order=1, run_id="run_eval", task_id="pilot_task", product_id="greenfield",
                condition_id="orca__off", ade="orca", harness=None, agentskit="off",
                replicate=1, randomization_seed=1,
            )
            context = StepContext(
                assignment=assignment, bundle=bundle,
                step=ConditionStep("merge", "merge", "controller"), attempt=0,
                worktree=root, branch="benchmark/run_eval",
                idempotency_key="run_eval:pre-merge-verification",
                deadline_epoch_ms=None, accounting_tool="verification-accounting",
            )
            executor = CodexEvaluatorV12RoleExecutor(Transport())
            expected = {
                "verified_gates": sorted(PRE_MERGE_QUALITY_GATES),
                "product_quality_score": 91,
            }
            self.assertFalse(CodexV12CompletionVerifier(executor).verify(context, expected))
            events = [json.loads(line) for line in bundle.ledger.path.read_text().splitlines()]
            self.assertEqual(
                {event["event_type"] for event in events},
                {"backend.attempt.effective-work", "backend.attempt.external-wait",
                 "backend.attempt.orchestration-overhead"},
            )
