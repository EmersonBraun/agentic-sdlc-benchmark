"""Evaluate the explicit semantic-parity evidence required by the pilot."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
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
REPO_ROOT = Path(__file__).resolve().parents[3]
TOOLCHAIN_REFS = {
    "controller/scripts/build_semantic_parity_matrix.py",
    "controller/src/benchmark_controller/semantic_parity.py",
}
COMPONENT_REFS = {
    "orca": {"adapters/orca-v1.1-lifecycle-probe-attestation-5.json", "controller/tests/test_orca.py"},
    "agent-orchestrator": {"adapters/agent-orchestrator-v1.1-execution-attestation.json", "controller/tests/test_ao_component_readiness.py"},
    "compozy": {"adapters/compozy-v1.1-component-readiness-attestation.json", "controller/tests/test_compozy.py", "controller/tests/test_compozy_lifecycle.py"},
    "reference": {"controller/src/benchmark_controller/harness_adapters.py", "controller/tests/test_adapters.py"},
    "openhands-sdk": {"adapters/openhands-sdk-v1.1-readiness-attestation.json", "controller/tests/test_openhands_probe.py"},
    "mini-swe-agent": {"adapters/mini-swe-cli-bridge-attestation-v1.1.json", "controller/tests/test_mini_swe_cli_model.py"},
    "off": {"controller/src/benchmark_controller/agentskit.py", "controller/tests/test_agentskit.py"},
    "on": {"adapters/agentskit-v1.1-component-readiness-attestation.json", "controller/tests/test_agentskit_component_readiness.py"},
}
INVARIANT_GLOBAL_REFS = {
    "same_task_and_acceptance_contract": {"protocol/conditions-v1.1.json", "tasks/public/issue-index-v1.1.json"},
    "common_harness_capabilities": {"controller/src/benchmark_controller/adapters.py", "controller/src/benchmark_controller/harness_adapters.py"},
    "workspace_boundary": {"controller/src/benchmark_controller/external.py"},
    "permission_mode": {"protocol/protocol-v1.1.md"},
    "lifecycle_events": {"schemas/ledger-event.schema.json"},
    "append_only_ledger": {"controller/src/benchmark_controller/ledger.py"},
    "no_fallback_resolution": {"controller/src/benchmark_controller/pilot_executor.py", "controller/src/benchmark_controller/ade_adapters.py"},
}


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
    missing = list(
        key for key in REQUIRED_EVIDENCE_KEYS if document.get("status") != "verified" or evidence.get(key) != "verified"
    )
    matrix_bound = section != "semantic_parity" or _verify_matrix_binding(document, preflight)
    if not matrix_bound:
        missing.append("matrix_binding")
    return SemanticParityReport(not missing, tuple(missing))


def _verify_matrix_binding(document: Mapping[str, Any], preflight: Mapping[str, Any]) -> bool:
    name = document.get("matrix")
    expected_hash = document.get("matrix_sha256")
    if not isinstance(name, str) or Path(name).name != name or not isinstance(expected_hash, str):
        return False
    path = REPO_ROOT / "adapters" / name
    try:
        payload = path.read_bytes()
        matrix = json.loads(payload)
    except (OSError, json.JSONDecodeError):
        return False
    if hashlib.sha256(payload).hexdigest() != expected_hash or not isinstance(matrix, Mapping):
        return False
    conditions_path = REPO_ROOT / "protocol/conditions-v1.1.json"
    if matrix.get("conditions_sha256") != hashlib.sha256(conditions_path.read_bytes()).hexdigest():
        return False
    expected_statuses = {
        factor: {
            key: value.get("status")
            for key, value in sorted(preflight.get(factor, {}).items())
            if isinstance(value, Mapping)
        }
        for factor in ("ade", "harness", "agentskit")
    }
    if matrix.get("component_statuses") != expected_statuses:
        return False
    conditions = matrix.get("conditions")
    source_hashes = matrix.get("source_hashes")
    if (
        matrix.get("schema_version") != "semantic-parity-matrix-v1.1"
        or matrix.get("protocol_version") != "v1.1"
        or matrix.get("status") != "verified"
        or matrix.get("condition_count") != 18
        or matrix.get("invariant_count") != 7
        or matrix.get("verification_count") != 126
        or matrix.get("integration_verification_count") != 18
        or not isinstance(conditions, list)
        or len(conditions) != 18
        or not isinstance(source_hashes, Mapping)
        or document.get("conditions_verified") != 18
        or document.get("invariants_per_condition") != 7
        or document.get("verification_count") != 126
    ):
        return False
    expected_combinations: set[tuple[str, str, str, str]] = set()
    for ade in ("orca", "agent-orchestrator", "compozy"):
        for harness in ("reference", "openhands-sdk", "mini-swe-agent"):
            for agentskit in ("off", "on"):
                expected_combinations.add((f"{ade}__{harness}__{agentskit}", ade, harness, agentskit))
    observed_combinations: set[tuple[str, str, str, str]] = set()
    integration_refs: set[str] = set()
    for condition in conditions:
        if not isinstance(condition, Mapping) or condition.get("verified") is not True:
            return False
        condition_id = condition.get("condition_id")
        factors = condition.get("factors")
        integration_ref = condition.get("integration_evidence_ref")
        invariants = condition.get("invariants")
        if (
            not isinstance(condition_id, str)
            or not isinstance(factors, Mapping)
            or not isinstance(integration_ref, str)
            or not integration_ref
            or integration_ref not in source_hashes
            or not isinstance(invariants, Mapping)
        ):
            return False
        integration_refs.add(integration_ref)
        integration_path = (REPO_ROOT / integration_ref).resolve()
        if not integration_path.is_relative_to(REPO_ROOT):
            return False
        try:
            integration = json.loads(integration_path.read_text())
        except (OSError, json.JSONDecodeError):
            return False
        if not isinstance(integration, Mapping):
            return False
        integration_invariants = integration.get("invariants")
        if (
            integration.get("schema_version") != "condition-integration-v1.1"
            or
            integration.get("status") != "passed"
            or integration.get("analysis_eligible") is not False
            or integration.get("terminal_state") != "completed"
            or integration.get("condition_id") != condition_id
            or not isinstance(integration.get("run_id"), str)
            or integration.get("factors") != dict(factors)
            or not isinstance(integration_invariants, Mapping)
            or set(integration_invariants) != set(REQUIRED_EVIDENCE_KEYS)
            or any(value != "passed" for value in integration_invariants.values())
        ):
            return False
        integration_evidence = integration.get("evidence")
        if not isinstance(integration_evidence, Mapping) or set(integration_evidence) != {"probe", "ledger", "manifest", "observation"}:
            return False
        evidence_payloads: dict[str, bytes] = {}
        for evidence_kind, evidence_record in integration_evidence.items():
            if not isinstance(evidence_record, Mapping):
                return False
            evidence_path = evidence_record.get("path")
            evidence_hash = evidence_record.get("sha256")
            if not isinstance(evidence_path, str) or not isinstance(evidence_hash, str):
                return False
            expected_suffix = {"probe": ".py", "ledger": ".jsonl", "manifest": ".json", "observation": ".json"}[evidence_kind]
            if not evidence_path.endswith(expected_suffix):
                return False
            target = (REPO_ROOT / evidence_path).resolve()
            if not target.is_relative_to(REPO_ROOT):
                return False
            try:
                evidence_payloads[evidence_kind] = target.read_bytes()
                if hashlib.sha256(evidence_payloads[evidence_kind]).hexdigest() != evidence_hash:
                    return False
            except OSError:
                return False
        try:
            probe_source = evidence_payloads["probe"].decode()
            compile(probe_source, integration_evidence["probe"]["path"], "exec")
            manifest = json.loads(evidence_payloads["manifest"])
            observation = json.loads(evidence_payloads["observation"])
            ledger_events = [json.loads(line) for line in evidence_payloads["ledger"].splitlines() if line.strip()]
        except (UnicodeDecodeError, SyntaxError, json.JSONDecodeError):
            return False
        run_id = integration["run_id"]
        if "CONDITION_INTEGRATION_PROBE_VERSION = \"v1.1\"" not in probe_source:
            return False
        if not isinstance(manifest, Mapping) or not isinstance(observation, Mapping) or len(ledger_events) != 7:
            return False
        identity = {"run_id": run_id, "condition_id": condition_id, "factors": dict(factors)}
        if (
            manifest.get("schema_version") != "condition-integration-manifest-v1.1"
            or manifest.get("terminal_state") != "completed"
            or any(manifest.get(key) != value for key, value in identity.items())
            or observation.get("schema_version") != "condition-integration-observation-v1.1"
            or observation.get("status") != "passed"
            or observation.get("terminal_state") != "completed"
            or observation.get("invariants") != {key: "passed" for key in REQUIRED_EVIDENCE_KEYS}
            or any(observation.get(key) != value for key, value in identity.items())
            or observation.get("probe_sha256") != integration_evidence["probe"]["sha256"]
            or observation.get("ledger_sha256") != integration_evidence["ledger"]["sha256"]
            or observation.get("manifest_sha256") != integration_evidence["manifest"]["sha256"]
        ):
            return False
        required_events = {f"integration.{key}" for key in REQUIRED_EVIDENCE_KEYS}
        observed_events: set[str] = set()
        for event in ledger_events:
            if (
                not isinstance(event, Mapping)
                or event.get("run_id") != run_id
                or event.get("condition_id") != condition_id
                or event.get("factors") != dict(factors)
                or event.get("status") != "completed"
            ):
                return False
            event_type = event.get("event_type")
            if isinstance(event_type, str):
                observed_events.add(event_type)
        if observed_events != required_events or len(observed_events) != len(ledger_events):
            return False
        observed_combinations.add((
            condition_id, str(factors.get("ade")), str(factors.get("harness")), str(factors.get("agentskit")),
        ))
        if set(invariants) != set(REQUIRED_EVIDENCE_KEYS):
            return False
        for invariant_name, evidence in invariants.items():
            if not isinstance(evidence, Mapping) or evidence.get("status") != "verified":
                return False
            refs = evidence.get("evidence_refs")
            if not isinstance(refs, list) or not refs:
                return False
            required_refs = (
                TOOLCHAIN_REFS
                | COMPONENT_REFS.get(str(factors.get("ade")), set())
                | COMPONENT_REFS.get(str(factors.get("harness")), set())
                | COMPONENT_REFS.get(str(factors.get("agentskit")), set())
                | INVARIANT_GLOBAL_REFS[invariant_name]
                | {integration_ref}
            )
            if not required_refs.issubset(set(refs)) or any(ref not in source_hashes for ref in refs):
                return False
    if observed_combinations != expected_combinations:
        return False
    if len(integration_refs) != 18:
        return False
    for reference, expected in source_hashes.items():
        if not isinstance(reference, str) or not isinstance(expected, str):
            return False
        source = (REPO_ROOT / reference).resolve()
        if not source.is_relative_to(REPO_ROOT):
            return False
        try:
            if hashlib.sha256(source.read_bytes()).hexdigest() != expected:
                return False
        except OSError:
            return False
    return True
