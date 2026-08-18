import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from benchmark_controller.agent_orchestrator_v12_executor import (
    AOCommandResult,
    AgentOrchestratorV12RoleExecutor,
)
from benchmark_controller.v12_native_backend import NativeStepRequest


class Transport:
    def __init__(self, workspace: Path, run_id: str, step: str):
        self.workspace = workspace
        self.run_id = run_id
        self.step = step
        self.calls = []

    def run(self, argv, *, timeout_seconds):
        self.calls.append(tuple(argv))
        if "project" in argv and "get" in argv:
            return AOCommandResult(json.dumps({"project": {"config": {
                "worker": {"agent": "grok", "agentConfig": {"model": "grok-4.5"}},
                "orchestrator": {"agent": "codex", "agentConfig": {"model": "gpt-5.4"}},
            }}}), "", 2)
        if "spawn" in argv:
            return AOCommandResult("spawned session ao-session-1", "", 3)
        if "session" in argv and "get" in argv:
            return AOCommandResult(json.dumps({"session": {"workspacePath": str(self.workspace)}}), "", 1)
        if argv[0] == "git":
            return AOCommandResult("a" * 40 + "\n", "", 1)
        if argv[:2] == ("tmux", "capture-pane"):
            sentinel = "V12_AO_" + hashlib.sha256(
                f"{self.run_id}:{self.step}".encode()
            ).hexdigest()[:20].upper()
            payload = json.dumps({"handoff_payload": {
                "requirements": "resolved", "implementation_plan": ["build"],
                "acceptance_criteria": ["passes"],
            }})
            return AOCommandResult(
                "prompt " + sentinel + "\ngpt-5.4\n" + payload + "\n" + sentinel, "", 1,
            )
        return AOCommandResult("{}", "", 1)


class AgentOrchestratorV12ExecutorTests(unittest.TestCase):
    def request(self, root: Path):
        task = root / "tasks/public/pilot_greenfield_service_readiness.md"
        task.parent.mkdir(parents=True)
        task.write_text("task")
        return NativeStepRequest(
            run_id="run_ao-test", condition_id="agent-orchestrator__off",
            task_id="pilot_greenfield_service_readiness", step="decomposition",
            role="planner_requirements_lead", provider="codex-cli", model="gpt-5.4",
            worktree=root, branch="benchmark/run_ao-test",
            idempotency_key="run_ao-test:decomposition:1", deadline_epoch_ms=None,
            task_path=task, handoff_path=None, agentskit_context_path=None,
        )

    def test_uses_native_orchestrator_session_and_validates_delegated_base(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workspace = root / "ao-worktree"
            workspace.mkdir()
            transport = Transport(workspace, "run_ao-test", "decomposition")
            executor = AgentOrchestratorV12RoleExecutor(
                "code-10x", ao_path=Path("/ao"), transport=transport,
            )
            result = executor.execute(self.request(root))
            self.assertEqual(result.status, "completed")
            self.assertEqual(result.metadata["handoff_payload"]["requirements"], "resolved")
            self.assertFalse(result.token_cost_accounting_observed)
            self.assertEqual(sum("spawn" in call for call in transport.calls), 1)
            executor.close()

    def test_semantic_stage_cache_prevents_duplicate_native_prompt(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workspace = root / "ao-worktree"
            workspace.mkdir()
            transport = Transport(workspace, "run_ao-test", "decomposition")
            executor = AgentOrchestratorV12RoleExecutor(
                "code-10x", ao_path=Path("/ao"), transport=transport,
            )
            request = self.request(root)
            first = executor.execute(request)
            second = executor.execute(request.__class__(**{
                **request.__dict__, "idempotency_key": "run_ao-test:decomposition:2",
            }))
            self.assertIs(first, second)
            self.assertEqual(sum("spawn" in call for call in transport.calls), 1)

    def test_expired_deadline_does_not_touch_ao(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workspace = root / "ao-worktree"
            workspace.mkdir()
            transport = Transport(workspace, "run_ao-test", "decomposition")
            request = self.request(root)
            request = request.__class__(**{**request.__dict__, "deadline_epoch_ms": 1})
            result = AgentOrchestratorV12RoleExecutor(
                "code-10x", ao_path=Path("/ao"), transport=transport,
            ).execute(request)
            self.assertEqual(result.status, "timeout")
            self.assertEqual(transport.calls, [])
