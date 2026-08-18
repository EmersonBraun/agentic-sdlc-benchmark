import json
import unittest
from pathlib import Path

from benchmark_controller.pilot import evaluate_pilot_gate


class PilotGateTests(unittest.TestCase):
    def test_current_preflight_blocks_all_primary_conditions(self) -> None:
        path = Path(__file__).resolve().parents[2] / "adapters" / "preflight-v1.0.json"
        report = evaluate_pilot_gate(json.loads(path.read_text(encoding="utf-8")))
        self.assertFalse(report.can_start)
        self.assertEqual(report.ready_conditions, 0)
        self.assertEqual(report.blocked_conditions, 18)
        self.assertEqual(len(report.conditions), 18)
        first = next(condition for condition in report.conditions if condition.condition_id == "orca__reference__off")
        self.assertEqual(
            first.factor_statuses,
            {"ade": "installed-not-ready", "harness": "contract-ready", "agentskit": "contract-ready"},
        )

    def test_gate_requires_every_factor_to_be_ready(self) -> None:
        preflight = {
            "protocol_version": "v1.0",
            "ade": {"orca": {"status": "installed-ready"}, "agent-orchestrator": {"status": "installed-ready"}, "compozy": {"status": "installed-ready"}},
            "harness": {"reference": {"status": "contract-ready"}, "openhands-sdk": {"status": "installed-ready"}, "mini-swe-agent": {"status": "installed-ready"}},
            "agentskit": {"off": {"status": "contract-ready"}, "on": {"status": "installed-ready"}},
        }
        report = evaluate_pilot_gate(preflight)
        self.assertTrue(report.can_start)
        self.assertEqual(report.ready_conditions, 18)

    def test_technical_gate_can_start_with_one_explicitly_ready_condition(self) -> None:
        preflight = {
            "protocol_version": "v1.1",
            "technical_pilot": {"allowed_conditions": ["compozy__reference__off"]},
            "ade": {
                "orca": {"status": "installed-not-ready"},
                "agent-orchestrator": {"status": "installed-not-ready"},
                "compozy": {"status": "installed-not-ready", "technical_pilot_status": "installed-ready"},
            },
            "harness": {
                "reference": {"status": "contract-ready"},
                "openhands-sdk": {"status": "dependency-resolution-failed"},
                "mini-swe-agent": {"status": "installed-not-ready"},
            },
            "agentskit": {
                "off": {"status": "contract-ready"},
                "on": {"status": "installed-not-ready"},
            },
        }
        report = evaluate_pilot_gate(preflight, gate_mode="technical-pilot")
        self.assertTrue(report.can_start)
        self.assertEqual(report.gate_mode, "technical-pilot")
        self.assertEqual(report.ready_conditions, 1)
        ready = [condition.condition_id for condition in report.conditions if condition.ready]
        self.assertEqual(ready, ["compozy__reference__off"])

    def test_published_condition_matrix_matches_current_gate(self) -> None:
        root = Path(__file__).resolve().parents[2]
        preflight = json.loads((root / "adapters" / "preflight-v1.0.json").read_text())
        snapshot = json.loads((root / "adapters" / "condition-readiness-v1.0.json").read_text())
        report = evaluate_pilot_gate(preflight)
        self.assertEqual(snapshot["schema_version"], "condition-readiness-v1.0")
        self.assertEqual(snapshot["ready_conditions"], report.ready_conditions)
        self.assertEqual(snapshot["blocked_conditions"], report.blocked_conditions)
        self.assertEqual(len(snapshot["conditions"]), 18)
