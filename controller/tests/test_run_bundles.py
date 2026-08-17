import json
import tempfile
import unittest
from pathlib import Path

from benchmark_controller.pilot_executor import PilotNotReadyError
from benchmark_controller.run_bundles import RunBundleWriter


def _ready_preflight() -> dict:
    evidence = {
        "same_task_and_acceptance_contract": "verified",
        "common_harness_capabilities": "verified",
        "workspace_boundary": "verified",
        "permission_mode": "verified",
        "lifecycle_events": "verified",
        "append_only_ledger": "verified",
        "no_fallback_resolution": "verified",
    }
    return {
        "protocol_version": "v1.1",
        "semantic_parity": {"status": "verified", "evidence": evidence},
        "ade": {name: {"status": "installed-ready"} for name in ("orca", "agent-orchestrator", "compozy")},
        "harness": {
            "reference": {"status": "contract-ready"},
            "openhands-sdk": {"status": "installed-ready"},
            "mini-swe-agent": {"status": "installed-ready"},
        },
        "agentskit": {"off": {"status": "contract-ready"}, "on": {"status": "installed-ready"}},
    }


class RunBundleWriterTests(unittest.TestCase):
    def test_blocked_gate_creates_no_partial_bundle(self) -> None:
        root = Path(__file__).resolve().parents[2]
        preflight = json.loads((root / "adapters" / "preflight-v1.1.json").read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "runs"
            with self.assertRaises(PilotNotReadyError):
                RunBundleWriter(preflight, output).create(
                    run_id="run_blocked-bundle",
                    task_id="pilot_greenfield_service_readiness",
                    product_id="greenfield",
                    ade="orca",
                    harness="reference",
                    agentskit="off",
                    replicate=1,
                    randomization_seed=7,
                    base_commit="a" * 40,
                    model_snapshots={},
                    component_versions={},
                )
            self.assertFalse((output / "run_blocked-bundle").exists())

    def test_ready_v1_1_bundle_has_manifest_and_empty_ledger(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            bundle = RunBundleWriter(_ready_preflight(), Path(directory)).create(
                run_id="run_ready-bundle",
                task_id="pilot_greenfield_service_readiness",
                product_id="greenfield",
                ade="orca",
                harness="reference",
                agentskit="off",
                replicate=1,
                randomization_seed=7,
                base_commit="a" * 40,
                model_snapshots={"planner": "gpt-5.4"},
                component_versions={"protocol": "v1.1"},
            )
            self.assertEqual(bundle.manifest["protocol_version"], "v1.1")
            self.assertEqual(bundle.manifest["terminal_state"], "NOT_APPLICABLE")
            self.assertTrue((bundle.directory / "manifest.json").is_file())
            self.assertTrue((bundle.directory / "artifact-index.json").is_file())
            self.assertTrue((bundle.directory / "evaluation-refs.json").is_file())
            self.assertTrue((bundle.directory / "ledger.jsonl").is_file())
            self.assertEqual((bundle.directory / "ledger.jsonl").read_text(encoding="utf-8"), "")
            self.assertEqual(bundle.condition.plan.protocol_version, "v1.1")


if __name__ == "__main__":
    unittest.main()
