"""Load and validate versioned frozen condition matrices."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


EXPECTED_ADE = {"orca", "agent-orchestrator", "compozy"}
EXPECTED_HARNESSES = {"reference", "openhands-sdk", "mini-swe-agent"}
EXPECTED_AGENTSKIT = {"off", "on"}
SUPPORTED_PROTOCOL_VERSIONS = {"v1.0", "v1.1", "v1.2"}


def load_conditions(path: Path) -> dict[str, Any]:
    """Load the matrix and reject structural drift."""

    document = json.loads(path.read_text(encoding="utf-8"))
    factors = document.get("factors", {})
    conditions = document.get("conditions", [])

    if document.get("protocol_version") not in SUPPORTED_PROTOCOL_VERSIONS:
        raise ValueError("Conditions must belong to a supported protocol version")
    if set(factors.get("ade", [])) != EXPECTED_ADE:
        raise ValueError("ADE factor does not match the protocol")
    if set(factors.get("agentskit", [])) != EXPECTED_AGENTSKIT:
        raise ValueError("AgentsKit factor does not match the protocol")

    protocol_version = document["protocol_version"]
    uses_harness_factor = protocol_version in {"v1.0", "v1.1"}
    expected_count = 18 if uses_harness_factor else 6
    if uses_harness_factor:
        if set(factors.get("harness", [])) != EXPECTED_HARNESSES:
            raise ValueError("Harness factor does not match the protocol")
    elif "harness" in factors:
        raise ValueError("Protocol v1.2 must not declare a harness factor")
    if len(conditions) != expected_count:
        raise ValueError(f"Expected {expected_count} conditions, found {len(conditions)}")

    ids: set[str] = set()
    expected: set[tuple[str, ...]] = set()
    for condition in conditions:
        condition_id = condition.get("condition_id")
        ade = condition.get("ade")
        agentskit = condition.get("agentskit")
        if not isinstance(condition_id, str) or condition_id in ids:
            raise ValueError(f"Duplicate or missing condition_id: {condition_id!r}")
        if ade not in EXPECTED_ADE or agentskit not in EXPECTED_AGENTSKIT:
            raise ValueError(f"Invalid condition factors: {condition!r}")
        harness = condition.get("harness")
        if uses_harness_factor and harness not in EXPECTED_HARNESSES:
            raise ValueError(f"Invalid condition factors: {condition!r}")
        if not uses_harness_factor and "harness" in condition:
            raise ValueError("Protocol v1.2 conditions must not declare a harness")
        ids.add(condition_id)
        expected.add((ade, harness, agentskit) if uses_harness_factor else (ade, agentskit))

    if len(expected) != expected_count:
        raise ValueError("Condition matrix does not contain every factor combination")
    return document
