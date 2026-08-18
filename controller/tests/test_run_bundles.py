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
            tasks = Path(directory) / "tasks"
            tasks.mkdir()
            with self.assertRaises(PilotNotReadyError):
                RunBundleWriter(preflight, output, tasks).create(
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
            root = Path(directory)
            tasks = root / "tasks"
            tasks.mkdir()
            (tasks / "pilot_greenfield_service_readiness.manifest.json").write_text(json.dumps({
                "task_id": "pilot_greenfield_service_readiness",
                "product_id": "greenfield",
                "phase": "pilot",
            }), encoding="utf-8")
            bundle = RunBundleWriter(_ready_preflight(), root / "runs", tasks).create(
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
            self.assertEqual(bundle.manifest["gate_mode"], "official-collection")
            self.assertTrue(bundle.manifest["analysis_eligible"])
            self.assertEqual(len(bundle.manifest["task_manifest_sha256"]), 64)
            self.assertEqual(bundle.manifest["terminal_state"], "NOT_APPLICABLE")
            self.assertTrue((bundle.directory / "manifest.json").is_file())
            self.assertTrue((bundle.directory / "artifact-index.json").is_file())
            self.assertTrue((bundle.directory / "evaluation-refs.json").is_file())
            self.assertTrue((bundle.directory / "ledger.jsonl").is_file())
            self.assertEqual((bundle.directory / "ledger.jsonl").read_text(encoding="utf-8"), "")
            self.assertEqual(bundle.condition.plan.protocol_version, "v1.1")

    def test_technical_bundle_is_explicitly_analysis_ineligible(self) -> None:
        root = Path(__file__).resolve().parents[2]
        preflight = json.loads((root / "adapters" / "preflight-v1.1.json").read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            tasks = temporary / "tasks"
            tasks.mkdir()
            (tasks / "pilot_greenfield_service_readiness.manifest.json").write_text(json.dumps({
                "task_id": "pilot_greenfield_service_readiness",
                "product_id": "greenfield",
                "phase": "pilot",
            }), encoding="utf-8")
            bundle = RunBundleWriter(
                preflight,
                temporary / "runs",
                tasks,
                gate_mode="technical-pilot",
            ).create(
                run_id="run_technical-bundle",
                task_id="pilot_greenfield_service_readiness",
                product_id="greenfield",
                ade="compozy",
                harness="reference",
                agentskit="off",
                replicate=1,
                randomization_seed=7,
                base_commit="a" * 40,
                model_snapshots={"planner": "gpt-5.4"},
                component_versions={"protocol": "v1.1"},
            )
            self.assertEqual(bundle.manifest["gate_mode"], "technical-pilot")
            self.assertFalse(bundle.manifest["analysis_eligible"])
            final = RunBundleWriter(
                preflight,
                temporary / "runs",
                tasks,
                gate_mode="technical-pilot",
            ).finalize(bundle, terminal_state="TECHNICAL_PASS")
            self.assertEqual(final["terminal_state"], "TECHNICAL_PASS")

    def test_finalize_records_terminal_state_and_rejects_second_close(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            tasks = root / "tasks"
            tasks.mkdir()
            (tasks / "pilot_greenfield_service_readiness.manifest.json").write_text(json.dumps({
                "task_id": "pilot_greenfield_service_readiness",
                "product_id": "greenfield",
                "phase": "pilot",
            }), encoding="utf-8")
            writer = RunBundleWriter(_ready_preflight(), root / "runs", tasks)
            bundle = writer.create(
                run_id="run_finalize-bundle",
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
            final = writer.finalize(
                bundle,
                terminal_state="MERGED",
                artifacts=[{"path": "result.patch", "sha256": "a" * 64, "visibility": "redacted"}],
            )
            self.assertEqual(final["terminal_state"], "MERGED")
            events = (bundle.directory / "ledger.jsonl").read_text(encoding="utf-8").splitlines()
            self.assertEqual(json.loads(events[-1])["event_type"], "run.terminal")
            with self.assertRaisesRegex(RuntimeError, "already finalized"):
                writer.finalize(bundle, terminal_state="FAILED")


if __name__ == "__main__":
    unittest.main()
