import hashlib
import json
import unittest
import tempfile
from unittest import mock
from pathlib import Path

from benchmark_controller.semantic_parity import REQUIRED_EVIDENCE_KEYS, evaluate_semantic_parity
import benchmark_controller.semantic_parity as semantic_parity


class SemanticParityMatrixTests(unittest.TestCase):
    def test_canonical_matrix_is_complete_and_hash_bound(self) -> None:
        root = Path(__file__).resolve().parents[2]
        preflight = json.loads((root / "adapters/preflight-v1.1.json").read_text())
        parity = preflight["semantic_parity"]
        matrix_path = root / "adapters" / parity["matrix"]
        matrix = json.loads(matrix_path.read_text())
        self.assertEqual(parity["matrix_sha256"], hashlib.sha256(matrix_path.read_bytes()).hexdigest())
        self.assertEqual(matrix["status"], "preconditions-verified")
        self.assertEqual(matrix["condition_count"], 18)
        self.assertEqual(matrix["precondition_verification_count"], 126)
        self.assertEqual(matrix["integration_verification_count"], 0)
        self.assertEqual(len({condition["condition_id"] for condition in matrix["conditions"]}), 18)
        for condition in matrix["conditions"]:
            self.assertFalse(condition["verified"])
            self.assertIsNone(condition["integration_evidence_ref"])
            self.assertEqual(set(condition["invariants"]), set(REQUIRED_EVIDENCE_KEYS))
            for invariant in condition["invariants"].values():
                self.assertEqual(invariant["status"], "precondition-verified")
                self.assertGreaterEqual(len(invariant["evidence_refs"]), 4)
        for reference, expected_hash in matrix["source_hashes"].items():
            self.assertEqual(expected_hash, hashlib.sha256((root / reference).read_bytes()).hexdigest())
        self.assertFalse(evaluate_semantic_parity(preflight).verified)

    def test_matrix_binding_is_required(self) -> None:
        preflight = {
            "semantic_parity": {
                "status": "verified",
                "evidence": {key: "verified" for key in REQUIRED_EVIDENCE_KEYS},
            }
        }
        report = evaluate_semantic_parity(preflight)
        self.assertFalse(report.verified)
        self.assertIn("matrix_binding", report.missing_evidence)

    def test_verified_matrix_requires_real_condition_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "adapters").mkdir()
            (root / "protocol").mkdir()
            conditions_path = root / "protocol/conditions-v1.1.json"
            conditions_path.write_text("{}")
            statuses = {
                "ade": {key: "installed-ready" for key in ("orca", "agent-orchestrator", "compozy")},
                "harness": {"reference": "contract-ready", "openhands-sdk": "installed-ready", "mini-swe-agent": "installed-ready"},
                "agentskit": {"off": "contract-ready", "on": "installed-ready"},
            }
            preflight = {factor: {key: {"status": status} for key, status in values.items()} for factor, values in statuses.items()}
            source_hashes = {}
            conditions = []
            for ade in statuses["ade"]:
                for harness in statuses["harness"]:
                    for agentskit in statuses["agentskit"]:
                        condition_id = f"{ade}__{harness}__{agentskit}"
                        factors = {"ade": ade, "harness": harness, "agentskit": agentskit}
                        run_id = f"run_{condition_id}"
                        directory_path = root / "integration" / condition_id
                        directory_path.mkdir(parents=True)
                        probe_path = directory_path / "probe.py"
                        probe_path.write_text('CONDITION_INTEGRATION_PROBE_VERSION = "v1.1"\n')
                        ledger_path = directory_path / "ledger.jsonl"
                        ledger_path.write_text("".join(
                            json.dumps({
                                "run_id": run_id, "condition_id": condition_id, "factors": factors,
                                "event_type": f"integration.{key}", "status": "completed",
                            }) + "\n" for key in REQUIRED_EVIDENCE_KEYS
                        ))
                        manifest_path = directory_path / "manifest.json"
                        manifest_path.write_text(json.dumps({
                            "schema_version": "condition-integration-manifest-v1.1", "run_id": run_id,
                            "condition_id": condition_id, "factors": factors, "terminal_state": "completed",
                        }))
                        observation_path = directory_path / "observation.json"
                        observation_path.write_text(json.dumps({
                            "schema_version": "condition-integration-observation-v1.1", "status": "passed",
                            "run_id": run_id, "condition_id": condition_id, "factors": factors,
                            "terminal_state": "completed", "invariants": {key: "passed" for key in REQUIRED_EVIDENCE_KEYS},
                            "probe_sha256": hashlib.sha256(probe_path.read_bytes()).hexdigest(),
                            "ledger_sha256": hashlib.sha256(ledger_path.read_bytes()).hexdigest(),
                            "manifest_sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
                        }))
                        evidence = {
                            kind: {"path": str(path.relative_to(root)), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
                            for kind, path in {
                                "probe": probe_path, "ledger": ledger_path,
                                "manifest": manifest_path, "observation": observation_path,
                            }.items()
                        }
                        integration_ref = f"integration/{condition_id}/attestation.json"
                        integration = {
                            "schema_version": "condition-integration-v1.1", "status": "passed",
                            "analysis_eligible": False, "terminal_state": "completed",
                            "run_id": run_id, "condition_id": condition_id, "factors": factors,
                            "invariants": {key: "passed" for key in REQUIRED_EVIDENCE_KEYS},
                            "evidence": evidence,
                        }
                        integration_path = root / integration_ref
                        integration_path.write_text(json.dumps(integration))
                        required = (
                            semantic_parity.TOOLCHAIN_REFS
                            | semantic_parity.COMPONENT_REFS[ade]
                            | semantic_parity.COMPONENT_REFS[harness]
                            | semantic_parity.COMPONENT_REFS[agentskit]
                            | {integration_ref}
                        )
                        invariants = {}
                        for invariant in REQUIRED_EVIDENCE_KEYS:
                            refs = required | semantic_parity.INVARIANT_GLOBAL_REFS[invariant]
                            invariants[invariant] = {"status": "verified", "evidence_refs": sorted(refs)}
                            for reference in refs:
                                target = root / reference
                                if not target.exists():
                                    target.parent.mkdir(parents=True, exist_ok=True)
                                    target.write_text(reference)
                                source_hashes[reference] = hashlib.sha256(target.read_bytes()).hexdigest()
                        conditions.append({
                            "condition_id": condition_id, "factors": factors, "verified": True,
                            "integration_evidence_ref": integration_ref, "invariants": invariants,
                        })
            matrix = {
                "schema_version": "semantic-parity-matrix-v1.1", "protocol_version": "v1.1",
                "status": "verified", "condition_count": 18, "invariant_count": 7,
                "verification_count": 126, "integration_verification_count": 18,
                "conditions_sha256": hashlib.sha256(conditions_path.read_bytes()).hexdigest(),
                "component_statuses": statuses, "source_hashes": source_hashes, "conditions": conditions,
            }
            matrix_path = root / "adapters/verified-matrix.json"
            matrix_path.write_text(json.dumps(matrix, sort_keys=True))
            parity = {
                "status": "verified", "matrix": matrix_path.name,
                "matrix_sha256": hashlib.sha256(matrix_path.read_bytes()).hexdigest(),
                "conditions_verified": 18, "invariants_per_condition": 7, "verification_count": 126,
                "evidence": {key: "verified" for key in REQUIRED_EVIDENCE_KEYS},
            }
            preflight["semantic_parity"] = parity
            with mock.patch.object(semantic_parity, "REPO_ROOT", root.resolve()):
                self.assertTrue(all(hashlib.sha256((root / path).read_bytes()).hexdigest() == value for path, value in source_hashes.items()))
                self.assertTrue(evaluate_semantic_parity(preflight).verified)
                first = root / conditions[0]["integration_evidence_ref"]
                first.write_text("[]")
                matrix["source_hashes"][conditions[0]["integration_evidence_ref"]] = hashlib.sha256(first.read_bytes()).hexdigest()
                matrix_path.write_text(json.dumps(matrix, sort_keys=True))
                parity["matrix_sha256"] = hashlib.sha256(matrix_path.read_bytes()).hexdigest()
                self.assertFalse(evaluate_semantic_parity(preflight).verified)
