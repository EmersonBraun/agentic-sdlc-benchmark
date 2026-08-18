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
        self.assertEqual(attestation["component_version"], "0.12.6")
        self.assertTrue(attestation["component_version_observed"])
        self.assertEqual(len(attestation["version_source_sha256"]), 64)
        self.assertEqual(attestation["operator"], "local-primary-operator")
        self.assertEqual(len(attestation["runtime_sha256"]), 64)
        self.assertEqual(len(attestation["workspace_commit_sha256"]), 64)
        self.assertIn("--confirm", attestation["probe_command"])
        self.assertTrue(attestation["model_configuration_observed"])
        self.assertTrue(attestation["permission_configuration_observed"])
        self.assertTrue(attestation["session"]["model_execution_observed"])
        self.assertTrue(attestation["provider_evidence"]["required_provider_sequence_complete"])
        self.assertTrue(attestation["provider_evidence"]["expected_reply_observed"])
        self.assertTrue(attestation["redaction"]["forbidden_values_absent"])
        self.assertGreater(attestation["provider_evidence"]["output_tokens_observed"], 0)
        self.assertEqual(attestation["model_identity"]["effective_models"], ["gpt-5.4"])
        self.assertEqual(attestation["model_identity"]["effective_providers"], ["openai"])
        self.assertTrue(attestation["workspace"]["clean"])
        self.assertTrue(attestation["workspace"]["head_matches_fixture"])
        self.assertTrue(attestation["workspace"]["complete_tree_matches_fixture"])
        self.assertEqual(attestation["cleanup"]["active_session_leak_count"], 0)
        self.assertTrue(attestation["cleanup"]["passed"])
        self.assertTrue(attestation["cleanup"]["target_session_terminated"])
        self.assertEqual(attestation["probe_sha256"], hashlib.sha256(runner.read_bytes()).hexdigest())
        self.assertEqual(preflight["ade"]["agent-orchestrator"]["status"], "installed-ready")
        self.assertNotEqual(preflight["semantic_parity"]["status"], "verified")
        self.assertEqual(preflight["semantic_parity"]["precondition_conditions_verified"], 18)

    def test_attestation_contains_no_raw_prompt_or_reply(self) -> None:
        root = Path(__file__).resolve().parents[2]
        raw = (root / "adapters" / "agent-orchestrator-v1.1-execution-attestation.json").read_text()
        self.assertNotIn("Read-only parity probe", raw)
        self.assertNotIn("PARITY_PROBE_READY", raw)
