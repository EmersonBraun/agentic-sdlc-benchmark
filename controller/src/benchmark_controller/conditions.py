"""Load and validate the frozen 18-condition matrix."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


EXPECTED_ADE = {"orca", "agent-orchestrator", "compozy"}
EXPECTED_HARNESSES = {"reference", "openhands-sdk", "mini-swe-agent"}
EXPECTED_AGENTSKIT = {"off", "on"}
SUPPORTED_PROTOCOL_VERSIONS = {"v1.0", "v1.1"}


def load_conditions(path: Path) -> dict[str, Any]:
    """Load the matrix and reject structural drift."""

    document = json.loads(path.read_text(encoding="utf-8"))
    factors = document.get("factors", {})
    conditions = document.get("conditions", [])

    if document.get("protocol_version") not in SUPPORTED_PROTOCOL_VERSIONS:
        raise ValueError("Conditions must belong to a supported protocol version")
    if set(factors.get("ade", [])) != EXPECTED_ADE:
        raise ValueError("ADE factor does not match the protocol")
    if set(factors.get("harness", [])) != EXPECTED_HARNESSES:
        raise ValueError("Harness factor does not match the protocol")
    if set(factors.get("agentskit", [])) != EXPECTED_AGENTSKIT:
        raise ValueError("AgentsKit factor does not match the protocol")
    if len(conditions) != 18:
        raise ValueError(f"Expected 18 conditions, found {len(conditions)}")

    ids: set[str] = set()
    expected: set[tuple[str, str, str]] = set()
    for condition in conditions:
        condition_id = condition.get("condition_id")
        ade = condition.get("ade")
        harness = condition.get("harness")
        agentskit = condition.get("agentskit")
        if not isinstance(condition_id, str) or condition_id in ids:
            raise ValueError(f"Duplicate or missing condition_id: {condition_id!r}")
        if ade not in EXPECTED_ADE or harness not in EXPECTED_HARNESSES or agentskit not in EXPECTED_AGENTSKIT:
            raise ValueError(f"Invalid condition factors: {condition!r}")
        ids.add(condition_id)
        expected.add((ade, harness, agentskit))

    if len(expected) != 18:
        raise ValueError("Condition matrix does not contain every factor combination")
    return document
