import hashlib
import json
from pathlib import Path
import unittest

from benchmark_controller.v12_integration import EXPECTED_CONDITIONS, verify_integration_record


class V12CanonicalIntegrationTests(unittest.TestCase):
    def test_all_six_canonical_records_are_live_and_valid(self) -> None:
        root = Path(__file__).resolve().parents[2]
        observed = set()
        for condition in EXPECTED_CONDITIONS:
            path = root / "adapters" / f"condition-integration-{condition.replace('__', '-')}-v1.2.json"
            observed.add(verify_integration_record(path).condition_id)
        self.assertEqual(observed, EXPECTED_CONDITIONS)

    def test_preflight_binds_verified_matrix_but_blocks_official_collection(self) -> None:
        root = Path(__file__).resolve().parents[2]
        preflight = json.loads((root / "adapters/preflight-v1.2.json").read_text())
        matrix_path = root / "adapters" / preflight["v12_semantic_parity"]["matrix"]
        self.assertEqual(
            hashlib.sha256(matrix_path.read_bytes()).hexdigest(),
            preflight["v12_semantic_parity"]["matrix_sha256"],
        )
        self.assertEqual(preflight["status"], "technical-pilot-ready")
        self.assertEqual(preflight["official_collection_status"], "blocked-runner-not-implemented")
        self.assertFalse(preflight["technical_pilot"]["analysis_eligible"])
