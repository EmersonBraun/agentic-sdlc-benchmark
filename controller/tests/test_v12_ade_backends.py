import unittest

from benchmark_controller.v12_ade_backends import resolve_v12_backend


class V12ADEBackendTests(unittest.TestCase):
    def test_all_ades_bind_identical_roles_without_fallback(self) -> None:
        for ade in ("orca", "agent-orchestrator", "compozy"):
            planner, executor = resolve_v12_backend(ade).topology()
            self.assertEqual((planner.provider, planner.model), ("codex-cli", "gpt-5.4"))
            self.assertEqual((executor.provider, executor.model), ("grok-cli", "grok-4.5"))
            self.assertNotEqual(planner.argv, executor.argv)

    def test_ao_uses_native_grok_harness(self) -> None:
        _, executor = resolve_v12_backend("agent-orchestrator").topology()
        self.assertIn("grok", executor.argv)
        self.assertIn("tui", executor.argv)

    def test_compozy_uses_custom_grok_cli_provider(self) -> None:
        _, executor = resolve_v12_backend("compozy").topology()
        self.assertIn("grok-cli", executor.argv)
