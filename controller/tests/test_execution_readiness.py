import json
import unittest
from pathlib import Path

from benchmark_controller.execution_readiness import evaluate_execution_readiness


class ExecutionReadinessTests(unittest.TestCase):
    def test_current_v11_report_names_every_operational_blocker(self) -> None:
        root = Path(__file__).resolve().parents[2]
        preflight = json.loads((root / "adapters" / "preflight-v1.1.json").read_text(encoding="utf-8"))
        report = evaluate_execution_readiness(preflight)

        self.assertFalse(report.can_start_official_collection)
        self.assertEqual(report.official_conditions_ready, 0)
        self.assertEqual(len(report.blockers), 6)
        self.assertEqual(
            {blocker.owner for blocker in report.blockers},
            {"operator", "upstream", "protocol"},
        )
        self.assertIn("compozy__reference__on", report.technical_conditions_ready)

    def test_all_ready_components_unlock_official_collection(self) -> None:
        preflight = {
            "protocol_version": "v1.1",
            "technical_pilot": {"allowed_conditions": []},
            "ade": {key: {"status": "installed-ready"} for key in ("orca", "agent-orchestrator", "compozy")},
            "harness": {
                key: {"status": "installed-ready"}
                for key in ("reference", "openhands-sdk", "mini-swe-agent")
            },
            "agentskit": {
                key: {"status": "installed-ready"}
                for key in ("off", "on")
            },
        }
        report = evaluate_execution_readiness(preflight)
        self.assertTrue(report.can_start_official_collection)
        self.assertEqual(report.official_conditions_ready, 18)
        self.assertEqual(report.blockers, ())
