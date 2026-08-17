"""Validate the isolated session-parity probe manifest without executing it."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

EXPECTED_ADES = {"orca", "agent-orchestrator", "compozy"}
REQUIRED_EVIDENCE = {
    "session_created",
    "lifecycle_started_and_completed",
    "external_event_normalized",
    "ledger_event_parenting_preserved",
    "session_terminated",
    "no_product_mutation",
    "no_cross_run_state_leakage",
}


@dataclass(frozen=True)
class SessionParityManifest:
    target_ades: tuple[str, ...]
    fixture_product_id: str
    operator_confirmation_required: bool
    default_executable: bool


def load_session_parity_manifest(path: Path) -> SessionParityManifest:
    document: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    if document.get("schema_version") != "session-parity-test-v1.0":
        raise ValueError("Session parity manifest schema is not v1.0")
    target_ades = document.get("target_ades")
    if set(target_ades or ()) != EXPECTED_ADES:
        raise ValueError("Session parity manifest must target all three ADEs")
    fixture = document.get("fixture", {})
    authorization = document.get("authorization", {})
    evidence = set(document.get("required_evidence", []))
    if fixture.get("product_id") != "greenfield":
        raise ValueError("Session parity fixture must use the greenfield product")
    if fixture.get("workspace_policy") != "ephemeral-copy-outside-repository":
        raise ValueError("Session parity fixture must be outside the repository")
    if evidence != REQUIRED_EVIDENCE:
        raise ValueError("Session parity evidence requirements drifted")
    if authorization.get("operator_confirmation_required") is not True:
        raise ValueError("Session parity requires operator confirmation")
    if authorization.get("default_executable") is not False:
        raise ValueError("Session parity must default to non-executable")
    return SessionParityManifest(
        target_ades=tuple(sorted(target_ades)),
        fixture_product_id=str(fixture["product_id"]),
        operator_confirmation_required=True,
        default_executable=False,
    )
