import hashlib
import json
from pathlib import Path
import unittest


class OrcaGrokV12EvidenceTests(unittest.TestCase):
    def test_canonical_attestation_is_passed_ledger_and_source_bound(self) -> None:
        root = Path(__file__).resolve().parents[2]
        attestation_path = root / "adapters/orca-grok-v1.2-readiness-attestation.json"
        ledger_path = root / "adapters/orca-grok-v1.2-readiness-ledger.jsonl"
        attestation = json.loads(attestation_path.read_text())
        self.assertEqual(attestation["status"], "passed")
        self.assertFalse(attestation["analysis_eligible"])
        self.assertTrue(attestation["runtime"]["ready"])
        self.assertTrue(attestation["runtime"]["graph_ready"])
        self.assertEqual(attestation["orchestration"]["dispatch_status"], "completed")
        self.assertEqual(attestation["orchestration"]["failure_count"], 0)
        self.assertTrue(attestation["orchestration"]["worker_done_accepted"])
        self.assertTrue(attestation["orchestration"]["delivery_acknowledged"])
        self.assertTrue(attestation["cleanup"]["verified"])
        self.assertTrue(attestation["workspace"]["clean"])
        self.assertEqual(attestation["ledger_sha256"], hashlib.sha256(ledger_path.read_bytes()).hexdigest())
        self.assertEqual(
            attestation["source_hashes"]["probe"],
            hashlib.sha256((root / "controller/scripts/probe_orca_grok_v12.py").read_bytes()).hexdigest(),
        )
        events = [json.loads(line) for line in ledger_path.read_text().splitlines() if line]
        self.assertGreater(len(events), 0)
        self.assertEqual([event["event_id"] for event in events], [f"evt_{index:06d}" for index in range(1, len(events) + 1)])
        self.assertNotIn("V12_ORCA_GROK45_READY", ledger_path.read_text())
