import hashlib
import json
import unittest
from pathlib import Path


class AgentsKitComponentReadinessTests(unittest.TestCase):
    def test_matched_pair_hashes_and_ledger_treatments_are_verifiable(self) -> None:
        root = Path(__file__).resolve().parents[2]
        attestation = json.loads(
            (root / "adapters" / "agentskit-v1.1-component-readiness-attestation.json").read_text()
        )
        pair = attestation["provider_backed_pair"]

        pair_path = (root / "adapters" / pair["pair"]).resolve()
        self.assertEqual(hashlib.sha256(pair_path.read_bytes()).hexdigest(), pair["pair_sha256"])

        for treatment in ("off", "on"):
            evidence = pair[treatment]
            run = root / "runs" / evidence["run_id"]
            for filename, key in (
                ("manifest.json", "manifest_sha256"),
                ("technical-pilot-attestation.json", "attestation_sha256"),
                ("ledger.jsonl", "ledger_sha256"),
            ):
                self.assertEqual(hashlib.sha256((run / filename).read_bytes()).hexdigest(), evidence[key])
            events = [json.loads(line) for line in (run / "ledger.jsonl").read_text().splitlines()]
            observed = sum(event["event_type"].startswith("agentskit.") for event in events)
            self.assertEqual(observed, evidence["agentskit_event_count"])

        self.assertEqual(pair["off"]["agentskit_event_count"], 0)
        self.assertEqual(pair["on"]["agentskit_event_count"], 6)
        self.assertFalse(attestation["source"]["agentskit_os_used"])


if __name__ == "__main__":
    unittest.main()
