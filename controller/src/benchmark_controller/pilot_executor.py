"""Fail-closed preparation boundary for the controlled pilot."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from .adapters import ExecutionPlan, build_execution_plan
from .pilot import ConditionReadiness, GateMode, PilotGateReport, evaluate_pilot_gate
from .semantic_parity import evaluate_semantic_parity


class PilotNotReadyError(RuntimeError):
    """Raised when a pilot condition cannot be prepared without bias."""


@dataclass(frozen=True)
class PreparedCondition:
    """A validated plan with no run, task, or external session side effect."""

    plan: ExecutionPlan
    condition: ConditionReadiness
    gate: PilotGateReport


class ConditionedPilotExecutor:
    """Prepare a condition under an explicit technical or collection gate."""

    def __init__(
        self,
        preflight: Mapping[str, Any],
        *,
        gate_mode: GateMode = "official-collection",
    ) -> None:
        self._preflight = preflight
        self._gate_mode = gate_mode

    def prepare_condition(
        self,
        *,
        run_id: str,
        ade: str,
        harness: str,
        agentskit: str,
    ) -> PreparedCondition:
        """Validate one condition without creating a run or invoking a tool."""

        gate = evaluate_pilot_gate(dict(self._preflight), gate_mode=self._gate_mode)
        condition_id = f"{ade}__{harness}__{agentskit}"
        condition = next(
            (item for item in gate.conditions if item.condition_id == condition_id),
            None,
        )
        if condition is None:
            raise PilotNotReadyError(f"Unknown pilot condition: {condition_id}")
        if self._gate_mode == "official-collection" and not gate.can_start:
            raise PilotNotReadyError(
                f"Pilot gate blocked: {gate.ready_conditions}/{len(gate.conditions)} "
                f"conditions ready; {condition_id} blocked by "
                + ", ".join(condition.missing_components)
            )
        if not condition.ready:
            raise PilotNotReadyError(
                f"Pilot condition blocked: {condition_id}: "
                + ", ".join(condition.missing_components)
            )

        parity_section = "technical_pilot" if self._gate_mode == "technical-pilot" else "semantic_parity"
        if self._gate_mode == "technical-pilot":
            technical = self._preflight.get("technical_pilot", {})
            allowed = technical.get("allowed_conditions", []) if isinstance(technical, Mapping) else []
            if condition_id not in allowed:
                raise PilotNotReadyError(f"Technical pilot condition is not preregistered: {condition_id}")
        parity = evaluate_semantic_parity(self._preflight, section=parity_section)
        if not parity.verified:
            raise PilotNotReadyError(
                "Semantic-parity gate is not verified; missing evidence: "
                + ", ".join(parity.missing_evidence)
            )

        plan = build_execution_plan(
            run_id=run_id,
            ade=ade,
            harness=harness,
            agentskit=agentskit,
            protocol_version=str(self._preflight.get("protocol_version", "v1.0")),
            preflight=self._preflight,
            gate_mode=self._gate_mode,
        )
        if not plan.semantic_parity:
            raise PilotNotReadyError("Resolved execution plan failed semantic-parity validation")
        if plan.fallback_used:
            raise PilotNotReadyError("Fallback adapter resolution is forbidden")
        return PreparedCondition(plan=plan, condition=condition, gate=gate)
