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
    if protocol_version not in {"v1.0", "v1.1"}:
        raise ValueError("Pilot preflight must target a supported protocol version")
    if gate_mode not in {"technical-pilot", "official-collection"}:
        raise ValueError(f"Unsupported gate mode: {gate_mode!r}")
    status_key = "technical_pilot_status" if gate_mode == "technical-pilot" else "status"
    factor_documents = {
        "ade": preflight.get("ade", {}),
        "harness": preflight.get("harness", {}),
        "agentskit": preflight.get("agentskit", {}),
    }
    readiness: list[ConditionReadiness] = []
    for ade, harness, agentskit in product(EXPECTED_ADE, EXPECTED_HARNESSES, EXPECTED_AGENTSKIT):
        selections = {"ade": ade, "harness": harness, "agentskit": agentskit}
        statuses = {
            factor: factor_documents[factor].get(value, {}).get(
                status_key,
                factor_documents[factor].get(value, {}).get("status", "missing"),
            )
            for factor, value in selections.items()
        }
        missing = tuple(
            f"{factor}:{value}:{statuses[factor]}"
            for factor, value in selections.items()
            if statuses[factor] not in READY_STATUSES
        )
        readiness.append(
            ConditionReadiness(
                condition_id=f"{ade}__{harness}__{agentskit}",
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
