"""Evaluate the explicit semantic-parity evidence required by the pilot."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

REQUIRED_EVIDENCE_KEYS = (
    "same_task_and_acceptance_contract",
    "common_harness_capabilities",
    "workspace_boundary",
    "permission_mode",
    "lifecycle_events",
    "append_only_ledger",
    "no_fallback_resolution",
)


@dataclass(frozen=True)
class SemanticParityReport:
    verified: bool
    missing_evidence: tuple[str, ...]


def evaluate_semantic_parity(
    preflight: Mapping[str, Any],
    *,
    section: str = "semantic_parity",
) -> SemanticParityReport:
    document = preflight.get(section, {})
    if not isinstance(document, Mapping):
        return SemanticParityReport(False, REQUIRED_EVIDENCE_KEYS)
    evidence = document.get("evidence", {})
    if not isinstance(evidence, Mapping):
        evidence = {}
    missing = tuple(
        key for key in REQUIRED_EVIDENCE_KEYS if document.get("status") != "verified" or evidence.get(key) != "verified"
    )
    return SemanticParityReport(not missing, missing)
