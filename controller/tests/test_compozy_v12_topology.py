import hashlib
import json
from pathlib import Path
import unittest


class CompozyV12TopologyEvidenceTests(unittest.TestCase):
    def test_canonical_attestation_is_passed_and_source_bound(self) -> None:
        root = Path(__file__).resolve().parents[2]
        path = root / "adapters/compozy-v1.2-topology-attestation.json"
        attestation = json.loads(path.read_text())
        self.assertEqual(attestation["status"], "passed")
        self.assertFalse(attestation["analysis_eligible"])
        topology = attestation["topology"]
        self.assertTrue(topology["same_session"])
        self.assertFalse(topology["fallback_used"])
        self.assertEqual(topology["planner"]["execution"]["providers"], ["codex"])
        self.assertEqual(topology["planner"]["execution"]["models"], ["gpt-5.4"])
        self.assertTrue(topology["planner"]["execution"]["sentinel_observed"])
        self.assertEqual(topology["executor"]["execution"]["providers"], ["grok-cli"])
        self.assertTrue(topology["executor"]["execution"]["sentinel_observed"])
        self.assertTrue(attestation["workspace"]["unchanged"])
        self.assertEqual(attestation["cleanup"]["new_grok_process_residual_count"], 0)
        self.assertFalse(attestation["cleanup"]["active_session_residual"])
        self.assertEqual(
            attestation["source_hashes"]["controller/scripts/probe_compozy_v12_topology.py"],
            hashlib.sha256((root / "controller/scripts/probe_compozy_v12_topology.py").read_bytes()).hexdigest(),
        )
        serialized = path.read_text()
        self.assertNotIn("V12_PLAN_", serialized)
        self.assertNotIn("V12_EXEC_", serialized)
