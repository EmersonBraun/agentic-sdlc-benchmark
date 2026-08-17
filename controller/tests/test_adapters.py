import unittest

from benchmark_controller.adapters import (
    AGENTSKIT_DESCRIPTORS,
    ADE_DESCRIPTORS,
    HARNESS_DESCRIPTORS,
    assert_live_adapter_ready,
    build_execution_plan,
)


class AdapterContractTests(unittest.TestCase):
    def test_catalog_has_three_levels_for_each_factor(self) -> None:
        self.assertEqual(set(ADE_DESCRIPTORS), {"orca", "agent-orchestrator", "compozy"})
        self.assertEqual(set(HARNESS_DESCRIPTORS), {"reference", "openhands-sdk", "mini-swe-agent"})
        self.assertEqual(set(AGENTSKIT_DESCRIPTORS), {"off", "on"})

    def test_every_primary_condition_resolves_without_fallback(self) -> None:
        for ade in ADE_DESCRIPTORS:
            for harness in HARNESS_DESCRIPTORS:
                for agentskit in AGENTSKIT_DESCRIPTORS:
                    plan = build_execution_plan(
                        run_id="run_adapter-contract",
                        ade=ade,
                        harness=harness,
                        agentskit=agentskit,
                    )
                    self.assertTrue(plan.semantic_parity)
                    self.assertFalse(plan.fallback_used)

    def test_live_execution_fails_closed_for_uninstalled_external_components(self) -> None:
        plan = build_execution_plan(
            run_id="run_fail-closed",
            ade="orca",
            harness="reference",
            agentskit="off",
        )
        with self.assertRaisesRegex(RuntimeError, "will not substitute"):
            assert_live_adapter_ready(plan)

    def test_invalid_factor_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "Unknown harness"):
            build_execution_plan(
                run_id="run_invalid-factor",
                ade="orca",
                harness="unknown",
                agentskit="off",
            )

