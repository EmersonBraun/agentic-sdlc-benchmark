import json
import unittest
from pathlib import Path

from benchmark_controller.pilot_executor import ConditionedPilotExecutor, PilotNotReadyError


class ConditionedPilotExecutorTests(unittest.TestCase):
    def test_current_preflight_fails_closed_before_plan_side_effects(self) -> None:
        root = Path(__file__).resolve().parents[2]
        preflight = json.loads((root / "adapters" / "preflight-v1.0.json").read_text(encoding="utf-8"))
        executor = ConditionedPilotExecutor(preflight)

        with self.assertRaisesRegex(PilotNotReadyError, "0/18 conditions ready"):
            executor.prepare_condition(
                run_id="run_blocked-pilot",
                ade="orca",
                harness="reference",
                agentskit="off",
            )

    def test_preparation_requires_verified_semantic_parity(self) -> None:
        preflight = {
            "protocol_version": "v1.0",
            "semantic_parity": {
                "status": "not-ready",
                "evidence": {"same_task_and_acceptance_contract": "verified"},
            },
            "ade": {
                "orca": {"status": "installed-ready"},
                "agent-orchestrator": {"status": "installed-ready"},
                "compozy": {"status": "installed-ready"},
            },
            "harness": {
                "reference": {"status": "contract-ready"},
                "openhands-sdk": {"status": "installed-ready"},
                "mini-swe-agent": {"status": "installed-ready"},
            },
            "agentskit": {
                "off": {"status": "contract-ready"},
                "on": {"status": "installed-ready"},
            },
        }

        with self.assertRaisesRegex(PilotNotReadyError, "Semantic-parity"):
            ConditionedPilotExecutor(preflight).prepare_condition(
                run_id="run_unverified-parity",
                ade="orca",
                harness="reference",
                agentskit="off",
            )

    def test_verified_synthetic_matrix_returns_plan_without_fallback(self) -> None:
        preflight = {
            "protocol_version": "v1.0",
            "semantic_parity": {
                "status": "verified",
                "evidence": {
                    "same_task_and_acceptance_contract": "verified",
                    "common_harness_capabilities": "verified",
                    "workspace_boundary": "verified",
                    "permission_mode": "verified",
                    "lifecycle_events": "verified",
                    "append_only_ledger": "verified",
                    "no_fallback_resolution": "verified",
                },
            },
            "ade": {
                "orca": {"status": "installed-ready"},
                "agent-orchestrator": {"status": "installed-ready"},
                "compozy": {"status": "installed-ready"},
            },
            "harness": {
                "reference": {"status": "contract-ready"},
                "openhands-sdk": {"status": "installed-ready"},
                "mini-swe-agent": {"status": "installed-ready"},
            },
            "agentskit": {
                "off": {"status": "contract-ready"},
                "on": {"status": "installed-ready"},
            },
        }

        prepared = ConditionedPilotExecutor(preflight).prepare_condition(
            run_id="run_synthetic-ready",
            ade="orca",
            harness="reference",
            agentskit="off",
        )

        self.assertEqual(prepared.condition.condition_id, "orca__reference__off")
        self.assertEqual(prepared.gate.ready_conditions, 18)
        self.assertTrue(prepared.plan.semantic_parity)
        self.assertFalse(prepared.plan.fallback_used)

    def test_current_v11_preflight_prepares_only_preregistered_technical_condition(self) -> None:
        root = Path(__file__).resolve().parents[2]
        preflight = json.loads((root / "adapters" / "preflight-v1.1.json").read_text(encoding="utf-8"))
        executor = ConditionedPilotExecutor(preflight, gate_mode="technical-pilot")

        prepared = executor.prepare_condition(
            run_id="run_technical-compozy-reference-off",
            ade="compozy",
            harness="reference",
            agentskit="off",
        )

        self.assertEqual(prepared.condition.condition_id, "compozy__reference__off")
        self.assertEqual(prepared.gate.ready_conditions, 1)
        self.assertEqual(prepared.plan.gate_mode, "technical-pilot")
        self.assertEqual(prepared.plan.ade.implementation_status, "installed-ready")

        with self.assertRaisesRegex(PilotNotReadyError, "not preregistered|blocked"):
            executor.prepare_condition(
                run_id="run_technical-orca-reference-off",
                ade="orca",
                harness="reference",
                agentskit="off",
            )
