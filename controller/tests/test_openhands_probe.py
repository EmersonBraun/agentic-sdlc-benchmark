import hashlib
import json
import sys
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from probe_openhands_sdk import parse_native_result


class OpenHandsProbeTests(unittest.TestCase):
    def test_parses_one_structured_result_amid_resolver_logs(self) -> None:
        payload = {
            "schema_version": "openhands-native-probe-v1.1", "versions": {
                "openhands-sdk": "1.42.1", "openhands-tools": "1.42.1",
                "openhands-workspace": "1.42.1", "openhands-agent-server": "1.42.1",
            }, "versions_exact": True,
            "workspace_type": "LocalWorkspace", "read_exit_code": 0, "read_marker_observed": True,
            "read_stdout_sha256": "a" * 64, "write_exit_code": 1, "write_denied": True,
            "write_stderr_sha256": "b" * 64, "workspace_tree_sha256": "c" * 64, "raw_content_in_result": False,
        }
        self.assertEqual(parse_native_result("resolver log\n" + json.dumps(payload)), payload)

    def test_rejects_missing_or_duplicated_structured_results(self) -> None:
        with self.assertRaises(ValueError):
            parse_native_result("resolver only")
        payload = json.dumps({"schema_version": "openhands-native-probe-v1.1"})
        with self.assertRaises(ValueError):
            parse_native_result(payload + "\n" + payload)


class OpenHandsReadinessEvidenceTests(unittest.TestCase):
    def test_attestation_is_exact_redacted_and_ledger_backed(self) -> None:
        root = Path(__file__).resolve().parents[2]
        attestation = json.loads((root / "adapters" / "openhands-sdk-v1.1-readiness-attestation.json").read_text())
        self.assertEqual(attestation["status"], "passed")
        self.assertEqual(attestation["resolver"], "uv")
        self.assertEqual(attestation["resolver_policy"], {"dependency_overrides": False, "no_deps": False, "pre_release": False, "require_hashes": True})
        self.assertTrue(attestation["native"]["versions_exact"])
        self.assertTrue(attestation["native"]["write_denied"])
        self.assertTrue(attestation["workspace_unchanged"])
        self.assertTrue(attestation["container_removed"])
        self.assertEqual(attestation["ledger_event_count"], 4)
        self.assertFalse(attestation["raw_output_persisted"])
        self.assertTrue(attestation["redaction_scan_passed"])
        for field, path in (
            ("probe_source_sha256", root / "controller" / "scripts" / "probe_openhands_sdk.py"),
            ("native_probe_source_sha256", root / "controller" / "scripts" / "openhands_native_probe.py"),
            ("command_bridge_source_sha256", root / "controller" / "scripts" / "openhands_command_bridge.py"),
            ("adapter_source_sha256", root / "controller" / "src" / "benchmark_controller" / "openhands_sdk.py"),
            ("controller_manifest_sha256", root / "controller" / "pyproject.toml"),
            ("validation_workflow_sha256", root / ".github" / "workflows" / "validate.yml"),
            ("ledger_sha256", root / "adapters" / "openhands-sdk-v1.1-probe-ledger.jsonl"),
            ("lock_sha256", root / "adapters" / "openhands-sdk-v1.1.requirements.lock"),
        ):
            self.assertEqual(attestation[field], hashlib.sha256(path.read_bytes()).hexdigest())
        events = [
            json.loads(line)
            for line in (root / "adapters" / "openhands-sdk-v1.1-probe-ledger.jsonl").read_text().splitlines()
        ]
        self.assertEqual(
            [(event["event_type"], event["status"]) for event in events],
            [
                ("harness.dependency.resolve", "completed"),
                ("harness.workspace.read", "completed"),
                ("harness.workspace.write", "blocked"),
                ("harness.cleanup", "completed"),
            ],
        )
