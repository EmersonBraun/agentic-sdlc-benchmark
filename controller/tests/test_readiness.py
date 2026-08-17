import json
import unittest
from pathlib import Path

from benchmark_controller.readiness import evaluate_adapter_readiness


class ReadinessTests(unittest.TestCase):
    def setUp(self) -> None:
        root = Path(__file__).resolve().parents[2]
        self.preflight = json.loads((root / "adapters" / "preflight-v1.0.json").read_text())

    def test_current_preflight_is_fail_closed(self) -> None:
        report = evaluate_adapter_readiness(self.preflight)
        self.assertEqual(report.ready_components, 2)
        self.assertEqual(report.blocked_components, 6)
        self.assertFalse(any(component.key == "compozy" and component.ready for component in report.components))

    def test_published_snapshot_matches_evaluator_counts(self) -> None:
        root = Path(__file__).resolve().parents[2]
        report = evaluate_adapter_readiness(self.preflight)
        snapshot = json.loads((root / "adapters" / "readiness-report-v1.0.json").read_text())
        self.assertEqual(snapshot["summary"]["ready_components"], report.ready_components)
        self.assertEqual(snapshot["summary"]["blocked_components"], report.blocked_components)
        self.assertEqual(snapshot["summary"]["pilot_conditions_ready"], 0)

    def test_external_component_needs_all_semantic_evidence(self) -> None:
        preflight = {
            "protocol_version": "v1.0",
            "ade": {
                "example": {
                    "status": "installed-ready",
                    "evidence": {
                        "doctor_core": "pass",
                        "registered_project": "example",
                        "global_permission_mode": "approve-reads",
                        "lifecycle_bridge": "live",
                        "ledger_bridge": "live",
                    },
                }
            },
            "harness": {},
            "agentskit": {},
        }
        report = evaluate_adapter_readiness(preflight)
        self.assertTrue(report.components[0].ready)

    def test_wrong_protocol_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "protocol v1.0"):
            evaluate_adapter_readiness({"protocol_version": "v0.9"})
