import hashlib
import json
from pathlib import Path
import unittest


class AOGrokV12EvidenceTests(unittest.TestCase):
    def test_canonical_attestation_is_live_passed_and_source_bound(self) -> None:
        root = Path(__file__).resolve().parents[2]
        attestation = json.loads((root / "adapters/ao-grok-v1.2-readiness-attestation.json").read_text())
        self.assertEqual(attestation["status"], "passed")
        self.assertFalse(attestation["analysis_eligible"])
        self.assertTrue(attestation["role_topology_configured"])
        self.assertTrue(attestation["effective_model_observed"])
        self.assertTrue(attestation["sentinel_observed"])
        self.assertFalse(attestation["trust_prompt_observed"])
        self.assertTrue(attestation["workspace"]["clean"])
        self.assertTrue(attestation["cleanup"]["verified"])
        self.assertEqual(
            attestation["source_hashes"]["probe"],
            hashlib.sha256((root / "controller/scripts/probe_ao_grok_v12.py").read_bytes()).hexdigest(),
        )
