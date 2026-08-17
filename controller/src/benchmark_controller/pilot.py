"""Pilot readiness gate; no run is created when a required factor is unavailable."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from itertools import product
from typing import Any

from .conditions import EXPECTED_ADE, EXPECTED_AGENTSKIT, EXPECTED_HARNESSES

READY_STATUSES = {"contract-ready", "installed-ready"}


@dataclass(frozen=True)
class ConditionReadiness:
    condition_id: str
    ready: bool
    missing_components: tuple[str, ...]
    factor_statuses: dict[str, str]


@dataclass(frozen=True)
class PilotGateReport:
    protocol_version: str
    can_start: bool
    ready_conditions: int
    blocked_conditions: int
    conditions: tuple[ConditionReadiness, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "protocol_version": self.protocol_version,
            "can_start": self.can_start,
            "ready_conditions": self.ready_conditions,
            "blocked_conditions": self.blocked_conditions,
            "conditions": [asdict(condition) for condition in self.conditions],
        }


def evaluate_pilot_gate(preflight: dict[str, Any]) -> PilotGateReport:
    """Evaluate every primary condition from immutable preflight statuses."""

    if preflight.get("protocol_version") != "v1.0":
        raise ValueError("Pilot preflight must target protocol v1.0")
    factor_documents = {
        "ade": preflight.get("ade", {}),
        "harness": preflight.get("harness", {}),
        "agentskit": preflight.get("agentskit", {}),
    }
    readiness: list[ConditionReadiness] = []
    for ade, harness, agentskit in product(EXPECTED_ADE, EXPECTED_HARNESSES, EXPECTED_AGENTSKIT):
        selections = {"ade": ade, "harness": harness, "agentskit": agentskit}
        statuses = {
            factor: factor_documents[factor].get(value, {}).get("status", "missing")
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
        protocol_version="v1.0",
        can_start=ready_count == len(readiness),
        ready_conditions=ready_count,
        blocked_conditions=len(readiness) - ready_count,
        conditions=tuple(sorted(readiness, key=lambda condition: condition.condition_id)),
    )
