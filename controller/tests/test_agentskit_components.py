import json
import tempfile
import unittest
from pathlib import Path

from benchmark_controller.agentskit import AgentsKitLedgerBridge
from benchmark_controller.agentskit_components import AgentsKitComponentActionBridge
from benchmark_controller.ledger import Ledger


class AgentsKitComponentActionBridgeTests(unittest.TestCase):
    def make_bridge(self, root: Path) -> AgentsKitComponentActionBridge:
        ledger = Ledger(root / "ledger.jsonl", run_id="run_component_actions", task_id="pilot_components")
        return AgentsKitComponentActionBridge(AgentsKitLedgerBridge(ledger, enabled=True))

    def test_maps_all_public_component_actions_and_redacts_content(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bridge = self.make_bridge(root)
            actions = [
                {"component": "doc-bridge", "operation": "lookup", "phase": "start"},
                {"component": "doc-bridge", "operation": "lookup", "phase": "complete", "durationMs": 2},
                {"component": "playbook", "operation": "step", "phase": "complete", "step": 1},
                {"component": "specialized-agents", "operation": "delegate", "phase": "start", "name": "requirements"},
                {"component": "specialized-agents", "operation": "delegate", "phase": "complete", "name": "requirements", "durationMs": 3},
                {"component": "code-review", "operation": "review", "phase": "complete", "durationMs": 4},
            ]
            events = [bridge.record(action) for action in actions]
            serialized = json.dumps(events)
            self.assertEqual(len(events), len(actions))
            self.assertNotIn("[redacted]", serialized)
            self.assertEqual(
                {event["event_type"] for event in events},
                {
                    "agentskit.tool.start",
                    "agentskit.tool.end",
                    "agentskit.progress",
                    "agentskit.agent.delegate.start",
                    "agentskit.agent.delegate.end",
                },
            )

    def test_rejects_unknown_component_and_invalid_phase(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            bridge = self.make_bridge(Path(directory))
            with self.assertRaises(ValueError):
                bridge.record({"component": "agentskit-os", "operation": "run", "phase": "start"})
            with self.assertRaises(ValueError):
                bridge.record({"component": "playbook", "operation": "step", "phase": "pending", "step": 1})

