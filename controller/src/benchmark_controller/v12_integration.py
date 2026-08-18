"""Evidence contracts for the six v1.2 ADE x AgentsKit integration probes."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping


EXPECTED_CONDITIONS = {
    f"{ade}__{agentskit}"
    for ade in ("orca", "agent-orchestrator", "compozy")
    for agentskit in ("off", "on")
}
REQUIRED_INVARIANTS = {
    "same_task",
    "same_base_commit",
    "role_topology",
    "workspace_boundary",
    "permission_policy",
    "lifecycle_cleanup",
    "no_fallback",
    "agentskit_attribution",
}


class V12IntegrationEvidenceError(ValueError):
    """Raised when an integration record cannot support semantic parity."""


@dataclass(frozen=True)
class VerifiedIntegration:
    condition_id: str
    evidence_file: str
    evidence_sha256: str


def verify_integration_record(path: Path) -> VerifiedIntegration:
    """Verify one live, analysis-ineligible condition record fail-closed."""

    raw = path.read_bytes()
    document = json.loads(raw)
    condition_id = document.get("condition_id")
    if condition_id not in EXPECTED_CONDITIONS:
        raise V12IntegrationEvidenceError("unknown condition_id")
    if document.get("schema_version") != "condition-integration-attestation-v1.2":
        raise V12IntegrationEvidenceError("unexpected schema_version")
    if document.get("protocol_version") != "v1.2" or document.get("analysis_eligible") is not False:
        raise V12IntegrationEvidenceError("integration probe must be v1.2 and analysis-ineligible")
    if document.get("status") != "passed" or document.get("live_execution") is not True:
        raise V12IntegrationEvidenceError("condition lacks a passing live execution")

    ade, agentskit = condition_id.rsplit("__", 1)
    factors = document.get("factors", {})
    if factors != {"ade": ade, "agentskit": agentskit}:
        raise V12IntegrationEvidenceError("factor binding does not match condition_id")
    if document.get("task_id") != "pilot_greenfield_service_readiness":
        raise V12IntegrationEvidenceError("technical pilot task drifted")

    invariants = document.get("invariants")
    if not isinstance(invariants, Mapping) or not REQUIRED_INVARIANTS.issubset(invariants):
        raise V12IntegrationEvidenceError("required invariants are incomplete")
    if any(invariants[name] != "passed" for name in REQUIRED_INVARIANTS):
        raise V12IntegrationEvidenceError("one or more invariants failed")

    events = document.get("agentskit", {})
    count = events.get("event_count") if isinstance(events, Mapping) else None
    public_only = events.get("public_only") if isinstance(events, Mapping) else None
    private_used = events.get("agentskit_os_used") if isinstance(events, Mapping) else None
    if agentskit == "off" and count != 0:
        raise V12IntegrationEvidenceError("OFF condition emitted AgentsKit events")
    if agentskit == "on" and (not isinstance(count, int) or count <= 0 or public_only is not True):
        raise V12IntegrationEvidenceError("ON condition lacks attributable public AgentsKit events")
    if private_used is not False:
        raise V12IntegrationEvidenceError("private AgentsKit components are prohibited")

    return VerifiedIntegration(condition_id, path.name, hashlib.sha256(raw).hexdigest())


def build_verified_matrix(records: list[Path], source_hashes: Mapping[str, str]) -> dict[str, Any]:
    """Build the unlock matrix only from exactly one valid record per condition."""

    verified = [verify_integration_record(path) for path in records]
    ids = [item.condition_id for item in verified]
    if len(verified) != 6 or set(ids) != EXPECTED_CONDITIONS or len(ids) != len(set(ids)):
        raise V12IntegrationEvidenceError("exactly one record for each of the six conditions is required")
    return {
        "schema_version": "semantic-parity-matrix-v1.2",
        "protocol_version": "v1.2",
        "status": "verified",
        "analysis_eligible": False,
        "scope": "technical integration readiness; not an effect estimate",
        "conditions": [
            {
                "condition_id": item.condition_id,
                "verified": True,
                "integration_evidence": item.evidence_file,
                "integration_evidence_sha256": item.evidence_sha256,
            }
            for item in sorted(verified, key=lambda item: item.condition_id)
        ],
        "source_hashes": dict(sorted(source_hashes.items())),
    }
