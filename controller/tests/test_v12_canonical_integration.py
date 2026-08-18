import hashlib
import json
from pathlib import Path
import unittest

from benchmark_controller.v12_integration import EXPECTED_CONDITIONS


class V12CanonicalIntegrationTests(unittest.TestCase):
    def test_all_six_canonical_records_are_scoped_as_ineligible_smokes(self) -> None:
        root = Path(__file__).resolve().parents[2]
        observed = set()
        for condition in EXPECTED_CONDITIONS:
            path = root / "adapters" / f"connectivity-smoke-{condition.replace('__', '-')}-v1.2.json"
            document = json.loads(path.read_text())
            observed.add(document["condition_id"])
            self.assertEqual(document["schema_version"], "condition-connectivity-smoke-attestation-v1.2")
            self.assertFalse(document["semantic_parity_eligible"])
            self.assertTrue(document["missing_gates"])
            self.assertEqual(document["invariants"]["no_fallback"], "not_evaluated")
            self.assertEqual(document["source_revision"]["git_commit"], "55fd50270f11c5c9a7a69d6f2e9d9d1a3db85498")
            self.assertTrue(document["source_revision"]["probe_sha256_matches_commit"])
        self.assertEqual(observed, EXPECTED_CONDITIONS)

    def test_preflight_binds_blocked_matrix_and_blocks_pilot_and_collection(self) -> None:
        root = Path(__file__).resolve().parents[2]
        preflight = json.loads((root / "adapters/preflight-v1.2.json").read_text())
        matrix_path = root / "adapters" / preflight["v12_semantic_parity"]["matrix"]
        self.assertEqual(
            hashlib.sha256(matrix_path.read_bytes()).hexdigest(),
            preflight["v12_semantic_parity"]["matrix_sha256"],
        )
        matrix = json.loads(matrix_path.read_text())
        self.assertEqual(preflight["status"], "connectivity-smoke-ready")
        self.assertEqual(preflight["technical_pilot_status"], "blocked-full-runner-and-evidence-contract")
        self.assertEqual(preflight["v12_semantic_parity"]["status"], "blocked")
        self.assertEqual(matrix["status"], "blocked")
        self.assertTrue(all(item["verified"] is False for item in matrix["conditions"]))
        self.assertEqual(preflight["official_collection_status"], "blocked-runner-not-implemented")
        self.assertFalse(preflight["technical_pilot"]["analysis_eligible"])
