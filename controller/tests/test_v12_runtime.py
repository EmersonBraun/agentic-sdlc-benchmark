from pathlib import Path
import tempfile
import unittest

from benchmark_controller.agent_orchestrator_v12_executor import AgentOrchestratorV12RoleExecutor
from benchmark_controller.compozy_v12_executor import CompozyV12RoleExecutor
from benchmark_controller.orca_v12_executor import OrcaV12RoleExecutor
from benchmark_controller.v12_runtime import build_v12_role_executor


class V12RuntimeFactoryTests(unittest.TestCase):
    def test_all_ades_share_the_neutral_frozen_evaluator(self):
        expected = {
            "compozy": CompozyV12RoleExecutor,
            "agent-orchestrator": AgentOrchestratorV12RoleExecutor,
            "orca": OrcaV12RoleExecutor,
        }
        with tempfile.TemporaryDirectory() as directory:
            for ade, executor_type in expected.items():
                executor, verifier = build_v12_role_executor(
                    ade, control_root=Path(directory), ao_project="benchmark",
                )
                self.assertIsInstance(executor, executor_type)
                self.assertIs(executor.evaluator, verifier.executor)
                self.assertEqual((verifier.provider, verifier.model), ("codex", "gpt-5.4-mini"))

    def test_unknown_ade_has_no_fallback(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, "unsupported"):
                build_v12_role_executor(
                    "unknown", control_root=Path(directory), ao_project="benchmark",
                )
