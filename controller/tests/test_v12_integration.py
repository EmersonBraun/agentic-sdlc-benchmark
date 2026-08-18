import json
from pathlib import Path
import tempfile
import unittest

from benchmark_controller.v12_integration import (
    EXPECTED_CONDITIONS,
    V12IntegrationEvidenceError,
    build_verified_matrix,
    verify_integration_record,
)


def record(condition_id: str) -> dict:
    ade, agentskit = condition_id.rsplit("__", 1)
    return {
        "schema_version": "condition-integration-attestation-v1.2",
        "protocol_version": "v1.2",
        "analysis_eligible": False,
        "live_execution": True,
        "status": "passed",
        "condition_id": condition_id,
        "task_id": "pilot_greenfield_service_readiness",
        "factors": {"ade": ade, "agentskit": agentskit},
        "invariants": {
            name: "passed"
            for name in (
                "same_task", "same_base_commit", "role_topology", "workspace_boundary",
                "permission_policy", "lifecycle_cleanup", "no_fallback", "agentskit_attribution",
            )
        },
        "agentskit": {
            "event_count": 0 if agentskit == "off" else 6,
            "public_only": agentskit == "on",
            "agentskit_os_used": False,
        },
    }


class V12IntegrationTests(unittest.TestCase):
    def test_matrix_requires_all_six_live_conditions(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = []
            for condition_id in EXPECTED_CONDITIONS:
                path = root / f"{condition_id}.json"
                path.write_text(json.dumps(record(condition_id)))
                paths.append(path)
            matrix = build_verified_matrix(paths, {"protocol/protocol-v1.2.md": "abc"})
            self.assertEqual(len(matrix["conditions"]), 6)
            self.assertFalse(matrix["analysis_eligible"])

    def test_off_fails_if_agentskit_event_is_observed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "record.json"
            document = record("orca__off")
            document["agentskit"]["event_count"] = 1
            path.write_text(json.dumps(document))
            with self.assertRaisesRegex(V12IntegrationEvidenceError, "OFF"):
                verify_integration_record(path)

    def test_on_fails_without_public_attribution(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "record.json"
            document = record("compozy__on")
            document["agentskit"]["public_only"] = False
            path.write_text(json.dumps(document))
            with self.assertRaisesRegex(V12IntegrationEvidenceError, "ON"):
                verify_integration_record(path)

    def test_private_agentskit_is_always_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "record.json"
            document = record("agent-orchestrator__on")
            document["agentskit"]["agentskit_os_used"] = True
            path.write_text(json.dumps(document))
            with self.assertRaisesRegex(V12IntegrationEvidenceError, "private"):
                verify_integration_record(path)
