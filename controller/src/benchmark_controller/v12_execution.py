"""Fail-closed execution contracts for the six-condition v1.2 cohort."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from .adapters import (
    ADE_DESCRIPTORS,
    AGENTSKIT_DESCRIPTORS,
    ComponentDescriptor,
    _descriptor_from_preflight,
)
from .conditions import EXPECTED_ADE, EXPECTED_AGENTSKIT
from .ids import validate_id
from .pilot import ConditionReadiness, GateMode, PilotGateReport, evaluate_pilot_gate
from .v12_ade_backends import NativeRoleLaunch, resolve_v12_backend

REPO_ROOT = Path(__file__).resolve().parents[3]
V12_REQUIRED_SOURCE_REFS = {
    "protocol/conditions-v1.2.json",
    "protocol/model-policy-v1.2.json",
    "protocol/protocol-v1.2.md",
    "controller/src/benchmark_controller/v12_execution.py",
    "controller/src/benchmark_controller/v12_ade_backends.py",
    "controller/src/benchmark_controller/v12_integration.py",
    "controller/src/benchmark_controller/v12_runner.py",
    "controller/src/benchmark_controller/v12_native_backend.py",
    "controller/src/benchmark_controller/compozy_v12_executor.py",
    "controller/src/benchmark_controller/agent_orchestrator_v12_executor.py",
    "controller/src/benchmark_controller/orca_v12_executor.py",
    "controller/src/benchmark_controller/codex_evaluator_v12.py",
    "controller/src/benchmark_controller/v12_evaluation_evidence.py",
    "controller/src/benchmark_controller/v12_evidence_collector.py",
    "controller/src/benchmark_controller/v12_runtime.py",
    "protocol/evaluator-rubric-v1.2.json",
    "schemas/controller-evidence-attestation-v1.2.schema.json",
    "schemas/controller-evidence-plan-v1.2.schema.json",
}


@dataclass(frozen=True)
class V12RoleBinding:
    role: str
    provider: str
    model: str


V12_ROLE_BINDINGS = (
    V12RoleBinding("planner_requirements_lead", "codex-cli", "gpt-5.4"),
    V12RoleBinding("executor_fixer", "grok-cli", "grok-4.5"),
    V12RoleBinding("independent_evaluator", "codex", "gpt-5.4-mini"),
)


@dataclass(frozen=True)
class V12ExecutionPlan:
    run_id: str
    protocol_version: str
    gate_mode: str
    ade: ComponentDescriptor
    agentskit: ComponentDescriptor
    role_bindings: tuple[V12RoleBinding, ...]
    native_launches: tuple[NativeRoleLaunch, ...]
    native_cli_loops: bool = True
    independent_harness_factor: bool = False
    semantic_parity: bool = True
    fallback_used: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "protocol_version": self.protocol_version,
            "gate_mode": self.gate_mode,
            "ade": _descriptor_dict(self.ade),
            "agentskit": _descriptor_dict(self.agentskit),
            "role_bindings": [asdict(binding) for binding in self.role_bindings],
            "native_launches": [launch.to_dict() for launch in self.native_launches],
            "native_cli_loops": self.native_cli_loops,
            "independent_harness_factor": self.independent_harness_factor,
            "semantic_parity": self.semantic_parity,
            "fallback_used": self.fallback_used,
        }


@dataclass(frozen=True)
class PreparedV12Condition:
    plan: V12ExecutionPlan
    condition: ConditionReadiness
    gate: PilotGateReport


class V12PilotNotReadyError(RuntimeError):
    """Raised before side effects when v1.2 evidence is incomplete."""


def build_v12_execution_plan(
    *, run_id: str, ade: str, agentskit: str, preflight: Mapping[str, Any], gate_mode: GateMode
) -> V12ExecutionPlan:
    validate_id(run_id, "run")
    if ade not in EXPECTED_ADE:
        raise ValueError(f"Unknown ADE adapter: {ade!r}")
    if agentskit not in EXPECTED_AGENTSKIT:
        raise ValueError(f"Unknown AgentsKit factor: {agentskit!r}")
    if preflight.get("protocol_version") != "v1.2":
        raise ValueError("v1.2 execution requires a v1.2 preflight")
    status_key = "technical_pilot_status" if gate_mode == "technical-pilot" else "status"
    ade_descriptor = _descriptor_from_preflight(ADE_DESCRIPTORS[ade], preflight, ade, status_key=status_key)
    agentskit_descriptor = _descriptor_from_preflight(
        AGENTSKIT_DESCRIPTORS[agentskit], preflight, agentskit, status_key=status_key
    )
    native_launches = resolve_v12_backend(ade).topology()
    return V12ExecutionPlan(
        run_id=run_id,
        protocol_version="v1.2",
        gate_mode=gate_mode,
        ade=ade_descriptor,
        agentskit=agentskit_descriptor,
        role_bindings=V12_ROLE_BINDINGS,
        native_launches=native_launches,
    )


class ConditionedV12PilotExecutor:
    def __init__(self, preflight: Mapping[str, Any], *, gate_mode: GateMode, repo_root: Path = REPO_ROOT) -> None:
        self._preflight = dict(preflight)
        self._gate_mode = gate_mode
        self._repo_root = repo_root.resolve()

    def prepare_condition(self, *, run_id: str, ade: str, agentskit: str) -> PreparedV12Condition:
        technical = self._preflight.get("technical_pilot", {})
        if self._gate_mode == "technical-pilot" and (
            not isinstance(technical, Mapping) or technical.get("analysis_eligible") is not False
        ):
            raise V12PilotNotReadyError("Technical pilot must be explicitly excluded from official analysis")
        gate = evaluate_pilot_gate(self._preflight, gate_mode=self._gate_mode)
        condition_id = f"{ade}__{agentskit}"
        condition = next((item for item in gate.conditions if item.condition_id == condition_id), None)
        if condition is None:
            raise V12PilotNotReadyError(f"Unknown pilot condition: {condition_id}")
        if not condition.ready:
            raise V12PilotNotReadyError(
                f"Pilot condition blocked: {condition_id}: " + ", ".join(condition.missing_components)
            )
        if self._gate_mode == "official-collection" and not gate.can_start:
            raise V12PilotNotReadyError("Official collection requires all six conditions to be ready")

        parity = self._preflight.get("v12_semantic_parity", {})
        if not isinstance(parity, Mapping) or not _verify_v12_parity(parity, self._repo_root):
            raise V12PilotNotReadyError("v1.2 semantic parity is not verified")
        matrix = json.loads((self._repo_root / "adapters" / str(parity["matrix"])).read_text())
        verified = [item["condition_id"] for item in matrix["conditions"] if item.get("verified") is True]
        if condition_id not in verified:
            raise V12PilotNotReadyError(f"Missing v1.2 integration evidence for {condition_id}")

        plan = build_v12_execution_plan(
            run_id=run_id, ade=ade, agentskit=agentskit, preflight=self._preflight, gate_mode=self._gate_mode
        )
        return PreparedV12Condition(plan=plan, condition=condition, gate=gate)


def _descriptor_dict(descriptor: ComponentDescriptor) -> dict[str, Any]:
    result = asdict(descriptor)
    result["capabilities"] = sorted(descriptor.capabilities)
    return result


def _verify_v12_parity(document: Mapping[str, Any], repo_root: Path) -> bool:
    name = document.get("matrix")
    expected_hash = document.get("matrix_sha256")
    if document.get("status") != "verified" or not isinstance(name, str) or Path(name).name != name:
        return False
    if not isinstance(expected_hash, str):
        return False
    path = repo_root / "adapters" / name
    try:
        payload = path.read_bytes()
        matrix = json.loads(payload)
    except (OSError, json.JSONDecodeError):
        return False
    expected_ids = {
        f"{ade}__{agentskit}"
        for ade in ("orca", "agent-orchestrator", "compozy")
        for agentskit in ("off", "on")
    }
    conditions = matrix.get("conditions") if isinstance(matrix, Mapping) else None
    if (
        hashlib.sha256(payload).hexdigest() != expected_hash
        or matrix.get("schema_version") != "semantic-parity-matrix-v1.2"
        or matrix.get("protocol_version") != "v1.2"
        or matrix.get("status") != "verified"
        or not isinstance(conditions, list)
        or len(conditions) != 6
        or {item.get("condition_id") for item in conditions if isinstance(item, Mapping)} != expected_ids
        or any(not isinstance(item, Mapping) or item.get("verified") is not True for item in conditions)
    ):
        return False
    source_hashes = matrix.get("source_hashes")
    if not isinstance(source_hashes, Mapping) or not V12_REQUIRED_SOURCE_REFS.issubset(source_hashes):
        return False
    for reference, digest in source_hashes.items():
        if not isinstance(reference, str) or not isinstance(digest, str):
            return False
        target = (repo_root / reference).resolve()
        if not target.is_relative_to(repo_root):
            return False
        try:
            if hashlib.sha256(target.read_bytes()).hexdigest() != digest:
                return False
        except OSError:
            return False
    return True
