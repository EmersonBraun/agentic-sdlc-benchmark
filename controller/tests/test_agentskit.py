import json
import tempfile
import unittest
from pathlib import Path

from benchmark_controller.agentskit import AgentsKitLedgerBridge, resolve_selection
from benchmark_controller.ledger import Ledger


class AgentsKitBridgeTests(unittest.TestCase):
    def test_resolves_full_on_selection_and_ablation(self) -> None:
        selection = resolve_selection(enabled=True, disabled_components=("code-review",))
        self.assertNotIn("code-review", selection.components)
        self.assertIn("telemetry", selection.components)

    def test_records_redacted_event_and_tokens(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ledger = Ledger(root / "ledger.jsonl", run_id="run_agentskit", task_id="pilot_smoke")
            bridge = AgentsKitLedgerBridge(ledger, enabled=True)
            event = bridge.on_event(
                {
                    "type": "llm:end",
                    "content": "secret model output",
                    "durationMs": 42,
                    "usage": {"promptTokens": 12, "completionTokens": 8},
                }
            )

            self.assertEqual(event["event_type"], "agentskit.llm.end")
            self.assertEqual(event["time_category"], "external_wait")
            self.assertEqual(event["tokens"], {"input": 12, "output": 8})
            self.assertNotIn("secret model output", json.dumps(event))

    def test_rejects_off_events_and_unknown_types(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ledger = Ledger(root / "ledger.jsonl", run_id="run_agentskit", task_id="pilot_smoke")
            off_bridge = AgentsKitLedgerBridge(ledger, enabled=False)
            with self.assertRaisesRegex(RuntimeError, "OFF"):
                off_bridge.on_event({"type": "agent:step", "step": 1, "action": "plan"})

            on_bridge = AgentsKitLedgerBridge(ledger, enabled=True)
            with self.assertRaisesRegex(ValueError, "Unsupported"):
                on_bridge.on_event({"type": "future:event"})

    def test_records_tool_metadata_without_arguments_or_results(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ledger = Ledger(root / "ledger.jsonl", run_id="run_agentskit", task_id="pilot_smoke")
            bridge = AgentsKitLedgerBridge(ledger, enabled=True)
            event = bridge.on_event(
                {
                    "type": "tool:end",
                    "name": "shell",
                    "result": "private result",
                    "durationMs": 3,
                }
            )
            self.assertEqual(event["time_category"], "effective_work")
            self.assertNotIn("private result", json.dumps(event))
