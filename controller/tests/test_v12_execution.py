import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from benchmark_controller.v12_execution import (
    ConditionedV12PilotExecutor,
    V12PilotNotReadyError,
    V12_REQUIRED_SOURCE_REFS,
)


def ready_preflight(root: Path, *, omit: str | None = None) -> dict:
    conditions = [
        f"{ade}__{agentskit}"
        for ade in ("orca", "agent-orchestrator", "compozy")
        for agentskit in ("off", "on")
    ]
    source_hashes = {}
    repository = Path(__file__).resolve().parents[2]
    for reference in V12_REQUIRED_SOURCE_REFS:
        target = root / reference
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((repository / reference).read_bytes())
        source_hashes[reference] = hashlib.sha256(target.read_bytes()).hexdigest()
    matrix = {
        "schema_version": "semantic-parity-matrix-v1.2",
        "protocol_version": "v1.2",
        "status": "verified",
        "conditions": [
            {"condition_id": item, "verified": item != omit}
            for item in conditions
        ],
        "source_hashes": source_hashes,
    }
    matrix_path = root / "adapters/semantic-parity-matrix-v1.2.json"
    matrix_path.parent.mkdir(parents=True, exist_ok=True)
    matrix_path.write_text(json.dumps(matrix), encoding="utf-8")
    return {
        "protocol_version": "v1.2",
        "technical_pilot": {"allowed_conditions": list(conditions), "analysis_eligible": False},
        "ade": {key: {"technical_pilot_status": "installed-ready"} for key in ("orca", "agent-orchestrator", "compozy")},
        "agentskit": {key: {"technical_pilot_status": "contract-ready"} for key in ("off", "on")},
        "v12_semantic_parity": {
            "status": "verified",
            "matrix": matrix_path.name,
            "matrix_sha256": hashlib.sha256(matrix_path.read_bytes()).hexdigest(),
        },
    }


class V12ExecutionTests(unittest.TestCase):
    def test_plan_freezes_roles_and_has_no_harness_factor(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            prepared = ConditionedV12PilotExecutor(
                ready_preflight(root), gate_mode="technical-pilot", repo_root=root
            ).prepare_condition(run_id="run_v12_test", ade="compozy", agentskit="on")
            plan = prepared.plan.to_dict()
            self.assertFalse(plan["independent_harness_factor"])
            self.assertEqual([item["provider"] for item in plan["role_bindings"]], ["codex-cli", "grok-cli", "codex"])
            self.assertEqual([item["provider"] for item in plan["native_launches"]], ["codex-cli", "grok-cli"])
            self.assertNotIn("harness", plan)

    def test_missing_condition_evidence_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            preflight = ready_preflight(root, omit="compozy__on")
            with self.assertRaisesRegex(V12PilotNotReadyError, "semantic parity"):
                ConditionedV12PilotExecutor(
                    preflight, gate_mode="technical-pilot", repo_root=root
                ).prepare_condition(run_id="run_v12_test", ade="compozy", agentskit="on")
