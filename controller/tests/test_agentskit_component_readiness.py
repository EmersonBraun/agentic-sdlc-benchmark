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
        recheck = attestation["fresh_contract_recheck"]
        recheck_path = root / "adapters" / recheck["attestation"]
        self.assertEqual(hashlib.sha256(recheck_path.read_bytes()).hexdigest(), recheck["attestation_sha256"])
        recheck_document = json.loads(recheck_path.read_text())
        self.assertEqual(recheck_document["source"]["commit"], attestation["source"]["commit"])
        self.assertEqual(
            recheck_document["integrated_fixture"]["contract_fingerprint_sha256"],
            recheck["integrated_contract_fingerprint_sha256"],
        )
        self.assertEqual(
            recheck_document["full_bridge_contract"]["contract_fingerprint_sha256"],
            recheck["full_bridge_contract_fingerprint_sha256"],
        )
        implementation = attestation["implementation"]
        implementation_path = root / implementation["technical_runner"]
        self.assertEqual(
            hashlib.sha256(implementation_path.read_bytes()).hexdigest(),
            implementation["technical_runner_sha256"],
        )

        manifests = {}
        pilot_attestations = {}
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
            manifests[treatment] = json.loads((run / "manifest.json").read_text())
            pilot_attestations[treatment] = json.loads(
                (run / "technical-pilot-attestation.json").read_text()
            )

        controlled_manifest_fields = (
            "task_id",
            "product_id",
            "base_commit",
            "randomization_seed",
            "model_snapshots",
        )
        for field in controlled_manifest_fields:
            self.assertEqual(manifests["off"][field], manifests["on"][field], field)
        self.assertEqual(manifests["off"]["task_id"], pair["same_task"])
        self.assertEqual(manifests["off"]["base_commit"], pair["same_base_commit"])
        self.assertEqual(manifests["off"]["condition_id"], "compozy__reference__off")
        self.assertEqual(manifests["on"]["condition_id"], "compozy__reference__on")
        self.assertEqual(pair["same_ade"], "compozy")
        self.assertEqual(pair["same_harness"], "reference")
        self.assertEqual(manifests["off"]["terminal_state"], "TECHNICAL_PASS")
        self.assertEqual(manifests["on"]["terminal_state"], "TECHNICAL_PASS")

        for treatment in ("off", "on"):
            pilot = pilot_attestations[treatment]
            self.assertEqual(pilot["provider"], pair["same_provider"])
            self.assertEqual(pilot["model"], pair["same_model"])
            self.assertTrue(pilot["cleanup"]["verified"])
            self.assertFalse(pilot["analysis_eligible"])

        self.assertEqual(pair["off"]["agentskit_event_count"], 0)
        self.assertEqual(pair["on"]["agentskit_event_count"], 6)
        self.assertTrue(pair["on"]["effective_work_deduplicated"])
        on_events = [
            json.loads(line)
            for line in (root / "runs" / pair["on"]["run_id"] / "ledger.jsonl").read_text().splitlines()
        ]
        timed_delegate_end_events = [
            event
            for event in on_events
            if event["event_type"] == "agentskit.agent.delegate.end"
        ]
        self.assertEqual(len(timed_delegate_end_events), 1)
        self.assertEqual(timed_delegate_end_events[0]["duration_ms"], 0)
        self.assertTrue(pilot_attestations["on"]["agentskit"]["public_only"])
        self.assertFalse(pilot_attestations["on"]["agentskit"]["agentskit_os_used"])
        for component in pilot_attestations["on"]["agentskit"]["components"].values():
            self.assertTrue(component["provenance_verified"])
            self.assertTrue(component["working_tree_clean"])
            self.assertTrue(component["materialized_from_lockfile"])
            self.assertEqual(len(component["executable_sha256"]), 64)
            self.assertTrue(component["repository"].startswith("https://github.com/AgentsKit-io/"))
        self.assertNotIn("agentskit_os", " ".join(manifests["on"]["component_versions"]))
        self.assertFalse(attestation["source"]["agentskit_os_used"])


if __name__ == "__main__":
    unittest.main()
