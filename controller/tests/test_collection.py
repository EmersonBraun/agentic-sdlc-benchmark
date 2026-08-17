import json
import tempfile
import unittest
from pathlib import Path

from benchmark_controller.collection import ExecutionOutcome, PilotCollectionCoordinator
from benchmark_controller.matrix import build_pilot_schedule
from benchmark_controller.run_bundles import RunBundleWriter


def _ready_preflight() -> dict:
    evidence = {key: "verified" for key in (
        "same_task_and_acceptance_contract", "common_harness_capabilities", "workspace_boundary",
        "permission_mode", "lifecycle_events", "append_only_ledger", "no_fallback_resolution",
    )}
    return {
        "protocol_version": "v1.1",
        "semantic_parity": {"status": "verified", "evidence": evidence},
        "ade": {name: {"status": "installed-ready"} for name in ("orca", "agent-orchestrator", "compozy")},
        "harness": {"reference": {"status": "contract-ready"}, "openhands-sdk": {"status": "installed-ready"}, "mini-swe-agent": {"status": "installed-ready"}},
        "agentskit": {"off": {"status": "contract-ready"}, "on": {"status": "installed-ready"}},
    }


class _FakeBackend:
    def execute(self, assignment, bundle):
        bundle.ledger.record(
            stage_id="implementation",
            actor="executor",
            event_type="fake.execution",
            time_category="effective_work",
            duration_ms=10,
            status="completed",
            payload={"condition_id": assignment.condition_id},
            tool="fake-backend",
        )
        return ExecutionOutcome("MERGED")


class CollectionCoordinatorTests(unittest.TestCase):
    def test_collects_and_finalizes_schedule_without_raw_backend_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            tasks = root / "tasks"
            tasks.mkdir()
            (tasks / "pilot_greenfield_service_readiness.manifest.json").write_text(json.dumps({
                "task_id": "pilot_greenfield_service_readiness", "product_id": "greenfield", "phase": "pilot",
            }), encoding="utf-8")
            writer = RunBundleWriter(_ready_preflight(), root / "runs", tasks)
            assignment = build_pilot_schedule(
                task_id="pilot_greenfield_service_readiness", product_id="greenfield", seed=3
            )[0]
            records = PilotCollectionCoordinator(writer, _FakeBackend()).collect(
                [assignment],
                base_commit="a" * 40,
                model_snapshots={"planner": "gpt-5.4"},
                component_versions={"protocol": "v1.1"},
            )
            self.assertEqual(records[0].terminal_state, "MERGED")
            manifest = json.loads((root / "runs" / assignment.run_id / "manifest.json").read_text())
            self.assertEqual(manifest["terminal_state"], "MERGED")
            ledger = (root / "runs" / assignment.run_id / "ledger.jsonl").read_text()
            self.assertIn("run.terminal", ledger)

    def test_backend_exception_becomes_infrastructure_failure(self) -> None:
        class BrokenBackend:
            def execute(self, assignment, bundle):
                raise RuntimeError("provider unavailable")

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            tasks = root / "tasks"
            tasks.mkdir()
            (tasks / "pilot_greenfield_service_readiness.manifest.json").write_text(json.dumps({
                "task_id": "pilot_greenfield_service_readiness", "product_id": "greenfield", "phase": "pilot",
            }), encoding="utf-8")
            assignment = build_pilot_schedule(
                task_id="pilot_greenfield_service_readiness", product_id="greenfield", seed=3
            )[0]
            records = PilotCollectionCoordinator(
                RunBundleWriter(_ready_preflight(), root / "runs", tasks), BrokenBackend()
            ).collect(
                [assignment], base_commit="a" * 40, model_snapshots={}, component_versions={}
            )
            self.assertEqual(records[0].terminal_state, "INFRASTRUCTURE_FAILURE")
            self.assertEqual(records[0].failure, {"error_type": "RuntimeError"})
