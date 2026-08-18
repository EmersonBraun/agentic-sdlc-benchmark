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
        self.assertEqual(len(report.blockers), 5)
        self.assertEqual(
            {blocker.owner for blocker in report.blockers},
            {"upstream", "protocol"},
        )
        self.assertNotIn("harness:mini-swe-agent", {blocker.component for blocker in report.blockers})
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

    def test_current_public_blocker_evidence_exists(self) -> None:
        root = Path(__file__).resolve().parents[2]
        report = json.loads(
            (root / "adapters" / "execution-readiness-v1.1.json").read_text(encoding="utf-8")
        )
        register = json.loads(
            (root / "adapters" / "blocker-register-v1.1.json").read_text(encoding="utf-8")
        )

        missing = [
            blocker["evidence_ref"]
            for blocker in report["blockers"]
            if not (root / blocker["evidence_ref"]).is_file()
        ]
        for blocker in register["blockers"]:
            missing.extend(
                f"adapters/{reference}"
                for reference in blocker["evidence_refs"]
                if not (root / "adapters" / reference).is_file()
                and not (root / reference).is_file()
            )
        self.assertEqual(missing, [])
