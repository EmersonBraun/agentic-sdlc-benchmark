import hashlib
import json
import unittest
from pathlib import Path


class AgentOrchestratorComponentReadinessTests(unittest.TestCase):
    def test_attestation_closes_only_component_local_gate(self) -> None:
        root = Path(__file__).resolve().parents[2]
        attestation = json.loads(
            (root / "adapters" / "agent-orchestrator-v1.1-execution-attestation.json").read_text()
        )
        preflight = json.loads((root / "adapters" / "preflight-v1.1.json").read_text())
        runner = root / "controller" / "scripts" / "probe_agent_orchestrator_execution.py"

        self.assertEqual(attestation["status"], "passed")
        self.assertFalse(attestation["analysis_eligible"])
        self.assertEqual(attestation["configured_model"], "gpt-5.4")
        self.assertTrue(attestation["model_configuration_observed"])
        self.assertTrue(attestation["session"]["model_execution_observed"])
        self.assertTrue(attestation["provider_evidence"]["required_provider_events_complete"])
        self.assertTrue(attestation["provider_evidence"]["expected_reply_observed"])
        self.assertFalse(attestation["provider_evidence"]["raw_content_persisted"])
        self.assertGreater(attestation["provider_evidence"]["output_tokens_observed"], 0)
        self.assertEqual(attestation["cleanup"]["active_session_leak_count"], 0)
        self.assertTrue(attestation["cleanup"]["passed"])
        self.assertEqual(attestation["probe_sha256"], hashlib.sha256(runner.read_bytes()).hexdigest())
        self.assertEqual(preflight["ade"]["agent-orchestrator"]["status"], "installed-ready")
        self.assertNotEqual(preflight["semantic_parity"]["status"], "verified")

    def test_attestation_contains_no_raw_prompt_or_reply(self) -> None:
        root = Path(__file__).resolve().parents[2]
        raw = (root / "adapters" / "agent-orchestrator-v1.1-execution-attestation.json").read_text()
        self.assertNotIn("Read-only parity probe", raw)
        self.assertNotIn("PARITY_PROBE_READY", raw)
