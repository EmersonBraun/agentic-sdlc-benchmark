import json
from pathlib import Path
import tempfile
import unittest

from benchmark_controller.compozy_v12_executor import CommandResult, CompozyV12RoleExecutor
from benchmark_controller.condition_runner import REQUIRED_QUALITY_GATES
from benchmark_controller.v12_native_backend import NativeStepRequest


class Transport:
    def __init__(self):
        self.calls = []

    def run_json(self, argv, *, timeout_seconds):
        self.calls.append(tuple(argv))
        if argv[:2] == ("config", "show"):
            return CommandResult({"config": {"providers": {
                "codex": {},
                "grok-cli": {
                    "command": "grok agent --model grok-4.5 --reasoning-effort low stdio",
                    "auth_mode": "native_cli", "env_policy": "filtered", "home_policy": "operator",
                    "credential_slots": [],
                },
            }}}, 2)
        if argv[:2] == ("session", "new"):
            return CommandResult({"id": "session-1"}, 3)
        if argv[:2] == ("session", "stop"):
            return CommandResult({"status": "stopped"}, 4)
        key = argv[argv.index("--idempotency-key") + 1]
        sentinel = "V12_" + __import__("hashlib").sha256(key.encode()).hexdigest()[:20].upper()
        provider = argv[argv.index("--provider") + 1]
        model = argv[argv.index("--model") + 1] if "--model" in argv else None
        prompt = argv[3]
        if "stage merge" in prompt:
            body = {"completion_proof": {
                "verified_gates": sorted(REQUIRED_QUALITY_GATES),
                "product_quality_score": 90, "merge_commit": "a" * 40,
            }}
        else:
            body = {"handoff_payload": {
                "requirements": "resolved", "implementation_plan": ["build"],
                "acceptance_criteria": ["passes"],
            }}
        text = json.dumps(body) + sentinel
        runtime = {"provider": provider}
        if model:
            runtime["model"] = model
        return CommandResult([
            {"type": "agent_message", "text": text, "prompt_runtime": runtime},
            {"type": "usage", "content": {"input_tokens": 10, "output_tokens": 5, "cost_usd": 0.01}},
            {"type": "done", "prompt_runtime": runtime},
        ], 20)


class RecoveringTransport(Transport):
    def run_json(self, argv, *, timeout_seconds):
        if argv[:2] == ["session", "prompt"]:
            self.calls.append(tuple(argv))
            raise RuntimeError("SSE scanner overflow")
        if argv[:2] == ("session", "events"):
            self.calls.append(tuple(argv))
            event_type = argv[argv.index("--type") + 1]
            runtime = {"provider": "codex", "model": "gpt-5.4"}
            key = "run_test:decomposition:1"
            sentinel = "V12_" + __import__("hashlib").sha256(key.encode()).hexdigest()[:20].upper()
            values = {
                "agent_message": [{"type": "agent_message", "text": json.dumps({
                    "handoff_payload": {"requirements": "resolved", "implementation_plan": ["build"],
                    "acceptance_criteria": ["passes"]},
                }) + sentinel, "prompt_runtime": runtime}],
                "usage": [{"type": "usage", "content": {"input_tokens": 1}}],
                "done": [{"type": "done", "prompt_runtime": runtime}],
            }
            return CommandResult(values[event_type], 1)
        return super().run_json(argv, timeout_seconds=timeout_seconds)


class CompozyV12ExecutorTests(unittest.TestCase):
    def request(self, root: Path, step="decomposition"):
        task = root / "tasks/public/pilot_greenfield_service_readiness.md"
        task.parent.mkdir(parents=True)
        task.write_text("task")
        return NativeStepRequest(
            run_id="run_test", condition_id="compozy__off", task_id="pilot_greenfield_service_readiness",
            step=step, role="planner_requirements_lead", provider="codex-cli", model="gpt-5.4",
            worktree=root, branch="benchmark/run_test", idempotency_key=f"run_test:{step}:1",
            deadline_epoch_ms=None, task_path=task, handoff_path=None, agentskit_context_path=None,
        )

    def test_executes_idempotently_with_frozen_provider_and_usage(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            transport = Transport()
            executor = CompozyV12RoleExecutor(root / "control", transport)
            request = self.request(root)
            first = executor.execute(request)
            second = executor.execute(request)
            self.assertEqual(first.status, "completed")
            self.assertIs(first, second)
            self.assertEqual(first.tokens["input"], 10)
            self.assertTrue(first.metadata["usage_observation"]["token_breakdown_observed"])
            self.assertEqual(first.metadata["handoff_payload"]["requirements"], "resolved")
            self.assertEqual(sum(call[:2] == ("session", "prompt") for call in transport.calls), 1)

    def test_merge_stops_workspace_session(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            transport = Transport()
            executor = CompozyV12RoleExecutor(root / "control", transport)
            result = executor.execute(self.request(root, "merge"))
            self.assertEqual(result.status, "completed")
            self.assertEqual(result.completion_proof["merge_commit"], "a" * 40)
            self.assertTrue(any(call[:2] == ("session", "stop") for call in transport.calls))

    def test_expired_deadline_never_starts_session(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            transport = Transport()
            request = self.request(root)
            request = request.__class__(**{**request.__dict__, "deadline_epoch_ms": 1})
            result = CompozyV12RoleExecutor(root / "control", transport).execute(request)
            self.assertEqual(result.status, "failed")
            self.assertEqual(transport.calls, [])

    def test_recovers_filtered_persisted_events_after_prompt_stream_overflow(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = CompozyV12RoleExecutor(
                root / "control", RecoveringTransport(),
            ).execute(self.request(root))
            self.assertEqual(result.status, "completed")
            self.assertEqual(result.metadata["handoff_payload"]["requirements"], "resolved")
