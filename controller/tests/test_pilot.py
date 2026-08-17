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

