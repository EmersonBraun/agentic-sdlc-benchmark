"""Pilot readiness gate; no run is created when a required factor is unavailable."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from itertools import product
from typing import Any, Literal

from .conditions import EXPECTED_ADE, EXPECTED_AGENTSKIT, EXPECTED_HARNESSES

READY_STATUSES = {"contract-ready", "installed-ready"}
GateMode = Literal["technical-pilot", "official-collection"]


@dataclass(frozen=True)
class ConditionReadiness:
    condition_id: str
    ready: bool
    missing_components: tuple[str, ...]
    factor_statuses: dict[str, str]


@dataclass(frozen=True)
class PilotGateReport:
    protocol_version: str
    gate_mode: GateMode
    can_start: bool
    ready_conditions: int
    blocked_conditions: int
    conditions: tuple[ConditionReadiness, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "protocol_version": self.protocol_version,
            "gate_mode": self.gate_mode,
            "can_start": self.can_start,
            "ready_conditions": self.ready_conditions,
            "blocked_conditions": self.blocked_conditions,
            "conditions": [asdict(condition) for condition in self.conditions],
        }


def evaluate_pilot_gate(
    preflight: dict[str, Any],
    *,
    gate_mode: GateMode = "official-collection",
) -> PilotGateReport:
    """Evaluate every condition for a technical pilot or official collection.

    Technical pilots use an explicit ``technical_pilot_status`` override and
    may start when at least one condition is ready. Official collection always
    uses the canonical status and remains an all-matrix 18/18 gate.
    """

    protocol_version = str(preflight.get("protocol_version", ""))
    if protocol_version not in {"v1.0", "v1.1", "v1.2"}:
        raise ValueError("Pilot preflight must target a supported protocol version")
    if gate_mode not in {"technical-pilot", "official-collection"}:
        raise ValueError(f"Unsupported gate mode: {gate_mode!r}")
    status_key = "technical_pilot_status" if gate_mode == "technical-pilot" else "status"
    technical = preflight.get("technical_pilot", {})
    allowed_conditions = set(technical.get("allowed_conditions", [])) if isinstance(technical, dict) else set()
    factor_documents: dict[str, Any] = {
        "ade": preflight.get("ade", {}),
        "agentskit": preflight.get("agentskit", {}),
    }
    if protocol_version != "v1.2":
        factor_documents["harness"] = preflight.get("harness", {})
    readiness: list[ConditionReadiness] = []
    harnesses: tuple[str | None, ...] = tuple(EXPECTED_HARNESSES) if protocol_version != "v1.2" else (None,)
    for ade, harness, agentskit in product(EXPECTED_ADE, harnesses, EXPECTED_AGENTSKIT):
        selections = {"ade": ade, "agentskit": agentskit}
        if harness is not None:
            selections["harness"] = harness
        statuses = {
            factor: factor_documents[factor].get(value, {}).get(
                status_key,
                factor_documents[factor].get(value, {}).get("status", "missing"),
            )
            for factor, value in selections.items()
        }
        missing_items = [
            f"{factor}:{value}:{statuses[factor]}"
            for factor, value in selections.items()
            if statuses[factor] not in READY_STATUSES
        ]
        condition_id = f"{ade}__{harness}__{agentskit}" if harness else f"{ade}__{agentskit}"
        if gate_mode == "technical-pilot" and condition_id not in allowed_conditions:
            missing_items.append("technical-pilot:not-preregistered")
        missing = tuple(missing_items)
        readiness.append(
            ConditionReadiness(
                condition_id=condition_id,
                ready=not missing,
                missing_components=missing,
                factor_statuses=statuses,
            )
        )
    ready_count = sum(condition.ready for condition in readiness)
    return PilotGateReport(
        protocol_version=protocol_version,
        gate_mode=gate_mode,
        can_start=ready_count > 0 if gate_mode == "technical-pilot" else ready_count == len(readiness),
        ready_conditions=ready_count,
        blocked_conditions=len(readiness) - ready_count,
        conditions=tuple(sorted(readiness, key=lambda condition: condition.condition_id)),
    )
