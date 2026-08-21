import hashlib
import json
from pathlib import Path
import subprocess
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


class ScoreTransport(Transport):
    def __init__(self, scores):
        super().__init__()
        self.scores = iter(scores)

    def run(self, argv, *, timeout_seconds):
        score = next(self.scores)
        result = super().run(argv, timeout_seconds=timeout_seconds)
        events = [json.loads(line) for line in result.stdout.splitlines()]
        proof = json.loads(events[1]["item"]["text"])
        proof["completion_proof"]["product_quality_score"] = score
        proof["completion_proof"]["scores"] = {name: score for name in RUBRIC_WEIGHTS}
        events[1]["item"]["text"] = json.dumps(proof)
        return CodexCommandResult("\n".join(json.dumps(event) for event in events), 25)


class CodexEvaluatorV12Tests(unittest.TestCase):
    def test_ledger_prefix_finds_attestation_snapshot_after_later_events(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ledger.jsonl"
            path.write_bytes(b"first\nsecond\nthird\n")
            expected = __import__("hashlib").sha256(b"first\nsecond\n").hexdigest()
            self.assertEqual(
                CodexEvaluatorV12RoleExecutor._ledger_prefix(path, expected),
                b"first\nsecond\n",
            )

    def request(self, root: Path, **overrides):
        worktree = root / "worktree"
        worktree.mkdir(exist_ok=True)
        task = worktree / "tasks/public/pilot_task.md"
        task.parent.mkdir(parents=True, exist_ok=True)
        task.write_text("task")
        manifest = worktree / "tasks/public/pilot_task.manifest.json"
        manifest.write_text(json.dumps({"task_id": "pilot_task"}))
        if not (worktree / ".git").exists():
            subprocess.run(("git", "init", "-q", str(worktree)), check=True)
            subprocess.run(("git", "-C", str(worktree), "config", "user.email", "test@example.test"), check=True)
            subprocess.run(("git", "-C", str(worktree), "config", "user.name", "Test"), check=True)
            subprocess.run(("git", "-C", str(worktree), "add", "."), check=True)
            subprocess.run(("git", "-C", str(worktree), "commit", "-qm", "fixture"), check=True)
        commit = subprocess.run(
            ("git", "-C", str(worktree), "rev-parse", "HEAD"),
            capture_output=True, text=True, check=True,
        ).stdout.strip()
        bundle = root / "bundle"
        evidence = bundle / "private-evaluation/controller-attestation.json"
        evidence.parent.mkdir(parents=True, exist_ok=True)
        ledger = bundle / "ledger.jsonl"
        ledger.touch()
        command_evidence = [{
            "kind": kind, "command_sha256": "a" * 64,
            "output_sha256": "b" * 64, "exit_code": 0,
        } for kind in ("build", "typecheck", "ci", "hidden-tests", "ledger-validation")]
        evidence.write_text(json.dumps({
            "schema_version": "controller-evidence-attestation-v1.2",
            "protocol_version": "v1.2", "task_id": "pilot_task",
            "task_manifest_sha256": hashlib.sha256(manifest.read_bytes()).hexdigest(),
            "product_commit": commit, "private_source_commit": "e" * 40,
            "hard_gates": {name: True for name in (
                "build", "typecheck", "ci", "essential-hidden-tests", "ledger"
            )},
            "hidden_test_summary": {
                "total": 4, "passed": 4, "failed": 0,
                "critical_mutants_killed": True, "noncritical_mutant_kill_rate": 0.9,
            },
            "ledger_prefix_sha256": hashlib.sha256(b"").hexdigest(),
            "command_evidence": command_evidence,
        }))
        values = dict(
            run_id="run_eval", condition_id="orca__off", task_id="pilot_task",
            step="review", role="independent_evaluator", provider="codex",
            model="gpt-5.4-mini", worktree=worktree, branch="benchmark/run_eval",
            idempotency_key="run_eval:review:1", deadline_epoch_ms=None,
            task_path=task, handoff_path=None,
            agentskit_context_path=None, evaluation_evidence_path=evidence,
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
            self.assertEqual(result.tokens, {"input": 24, "output": 16, "cached": 8, "reasoning": 4})
            self.assertEqual(result.metadata["evaluation_count"], 2)
            self.assertFalse(result.token_cost_accounting_observed)
            self.assertTrue(result.metadata["usage_observation"]["token_breakdown_observed"])
            self.assertFalse(result.metadata["usage_observation"]["cost_observed"])
            argv = transport.calls[0][0]
            self.assertIn(("-m", "gpt-5.4-mini"), tuple(zip(argv, argv[1:])))
            self.assertIn(("-s", "read-only"), tuple(zip(argv, argv[1:])))
            self.assertIn("--ephemeral", argv)
            self.assertIn("--skip-git-repo-check", argv)
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
        self.assertTrue(result.reason.startswith("invalid-evaluator-output:"))

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
            self.assertEqual(len(transport.calls), 4)

    def test_third_evaluation_resolves_initial_disagreement(self):
        with tempfile.TemporaryDirectory() as directory:
            transport = ScoreTransport((70, 90, 80))
            result = CodexEvaluatorV12RoleExecutor(transport).execute(
                self.request(Path(directory))
            )
            self.assertEqual(result.status, "completed")
            self.assertEqual(result.completion_proof["product_quality_score"], 80)
            self.assertEqual(result.metadata["evaluation_count"], 3)

    def test_persistent_three_way_disagreement_abstains(self):
        with tempfile.TemporaryDirectory() as directory:
            transport = ScoreTransport((50, 90, 70))
            result = CodexEvaluatorV12RoleExecutor(transport).execute(
                self.request(Path(directory))
            )
            self.assertEqual(result.status, "human-required")
            self.assertEqual(result.reason, "independent-evaluator-abstained")
            self.assertEqual(len(transport.calls), 3)

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

    def test_completion_verifier_composes_controller_owned_external_gates(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            task = root / "tasks/public/pilot_task.md"
            task.parent.mkdir(parents=True)
            task.write_text("task")
            bundle_dir = root / "bundle"
            bundle_dir.mkdir()
            bundle = type("Bundle", (), {
                "directory": bundle_dir,
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
                worktree=self.request(root).worktree, branch="benchmark/run_eval",
                idempotency_key="run_eval:pre-merge-verification",
                deadline_epoch_ms=None, accounting_tool="verification-accounting",
            )
            executor = CodexEvaluatorV12RoleExecutor(Transport())
            expected = {
                "verified_gates": sorted(PRE_MERGE_QUALITY_GATES),
                "product_quality_score": 91,
            }
            decision = CodexV12CompletionVerifier(executor).verify(context, expected)
            self.assertTrue(decision.accepted)
            self.assertEqual(decision.canonical_proof["product_quality_score"], 91)
            events = [json.loads(line) for line in bundle.ledger.path.read_text().splitlines()]
            self.assertEqual(
                {event["event_type"] for event in events},
                {"backend.attempt.effective-work", "backend.attempt.external-wait",
                 "backend.attempt.orchestration-overhead"},
            )
