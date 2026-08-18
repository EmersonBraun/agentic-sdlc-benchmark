#!/usr/bin/env python3
"""Build fail-closed semantic-parity evidence for the frozen v1.1 matrix."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
INVARIANTS = (
    "same_task_and_acceptance_contract",
    "common_harness_capabilities",
    "workspace_boundary",
    "permission_mode",
    "lifecycle_events",
    "append_only_ledger",
    "no_fallback_resolution",
)
READY = {"contract-ready", "installed-ready"}
COMPONENT_EVIDENCE = {
    "ade": {
        "orca": ("adapters/orca-v1.1-lifecycle-probe-attestation-5.json", "controller/tests/test_orca.py"),
        "agent-orchestrator": ("adapters/agent-orchestrator-v1.1-execution-attestation.json", "controller/tests/test_ao_component_readiness.py"),
        "compozy": ("adapters/compozy-v1.1-component-readiness-attestation.json", "controller/tests/test_compozy.py", "controller/tests/test_compozy_lifecycle.py"),
    },
    "harness": {
        "reference": (
            "controller/src/benchmark_controller/harness_adapters.py", "controller/tests/test_adapters.py",
        ),
        "openhands-sdk": ("adapters/openhands-sdk-v1.1-readiness-attestation.json", "controller/tests/test_openhands_probe.py"),
        "mini-swe-agent": ("adapters/mini-swe-cli-bridge-attestation-v1.1.json", "controller/tests/test_mini_swe_cli_model.py"),
    },
    "agentskit": {
        "off": (
            "controller/src/benchmark_controller/agentskit.py", "controller/tests/test_agentskit.py",
        ),
        "on": ("adapters/agentskit-v1.1-component-readiness-attestation.json", "controller/tests/test_agentskit_component_readiness.py"),
    },
}
GLOBAL_EVIDENCE = {
    "same_task_and_acceptance_contract": (
        "protocol/conditions-v1.1.json", "tasks/public/issue-index-v1.1.json",
    ),
    "common_harness_capabilities": (
        "controller/src/benchmark_controller/adapters.py",
        "controller/src/benchmark_controller/harness_adapters.py",
    ),
    "workspace_boundary": ("controller/src/benchmark_controller/external.py",),
    "permission_mode": ("protocol/protocol-v1.1.md",),
    "lifecycle_events": ("schemas/ledger-event.schema.json",),
    "append_only_ledger": ("controller/src/benchmark_controller/ledger.py",),
    "no_fallback_resolution": (
        "controller/src/benchmark_controller/pilot_executor.py",
        "controller/src/benchmark_controller/ade_adapters.py",
    ),
}
TOOLCHAIN_EVIDENCE = (
    "controller/scripts/build_semantic_parity_matrix.py",
    "controller/src/benchmark_controller/semantic_parity.py",
)


def digest(path: Path) -> str:
    if not path.is_file():
        raise FileNotFoundError(path)
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate_attestation(reference: str) -> None:
    if not reference.startswith("adapters/"):
        return
    document = json.loads((ROOT / reference).read_text())
    status = document.get("status")
    if status not in {"passed", "installed-ready"}:
        raise RuntimeError(f"component attestation is not passing: {reference}")
    if "orca-v1.1" in reference:
        valid = (
            document.get("orchestration", {}).get("worker_done_accepted") is True
            and document.get("orchestration", {}).get("delivery_acknowledged") is True
            and document.get("cleanup", {}).get("live_probe_terminals_remaining") == 0
            and document.get("cleanup", {}).get("workspace_mutated") is False
        )
    elif "agent-orchestrator" in reference:
        valid = (
            document.get("session", {}).get("model_execution_observed") is True
            and document.get("workspace", {}).get("clean") is True
            and document.get("cleanup", {}).get("passed") is True
        )
    elif "compozy" in reference:
        invariants = document.get("invariants", {})
        valid = isinstance(invariants, dict) and len(invariants) >= 7 and all(
            value in {"passed", "fail-closed", "forbidden"} for value in invariants.values()
        )
    elif "openhands" in reference:
        valid = (
            document.get("native", {}).get("read_marker_observed") is True
            and document.get("native", {}).get("write_denied") is True
            and document.get("workspace_unchanged") is True
            and document.get("container_removed") is True
            and document.get("redaction_scan_passed") is True
        )
    elif "mini-swe" in reference:
        probes = document.get("product_probes", [])
        valid = (
            isinstance(probes, list) and len(probes) >= 2
            and all(isinstance(probe, dict) and probe.get("status") == "passed" for probe in probes)
            and document.get("model_transport", {}).get("session_cleanup") == "passed"
            and document.get("model_transport", {}).get("api_credentials_used") is False
        )
    elif "agentskit" in reference:
        invariants = document.get("invariants", {})
        valid = isinstance(invariants, dict) and len(invariants) >= 7 and all(
            value == "passed" for value in invariants.values()
        )
    else:
        valid = False
    if not valid:
        raise RuntimeError(f"component attestation invariants failed: {reference}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--preflight", type=Path, default=ROOT / "adapters/preflight-v1.1.json")
    parser.add_argument("--conditions", type=Path, default=ROOT / "protocol/conditions-v1.1.json")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError("semantic-parity output must be new")

    preflight = json.loads(args.preflight.read_text())
    conditions_document = json.loads(args.conditions.read_text())
    conditions = conditions_document.get("conditions")
    if preflight.get("protocol_version") != "v1.1" or not isinstance(conditions, list) or len(conditions) != 18:
        raise RuntimeError("semantic parity requires the frozen v1.1 18-condition matrix")

    expected_conditions = {
        (f"{ade}__{harness}__{agentskit}", ade, harness, agentskit)
        for ade in ("orca", "agent-orchestrator", "compozy")
        for harness in ("reference", "openhands-sdk", "mini-swe-agent")
        for agentskit in ("off", "on")
    }
    observed_conditions = {
        (item.get("condition_id"), item.get("ade"), item.get("harness"), item.get("agentskit"))
        for item in conditions if isinstance(item, dict)
    }
    if observed_conditions != expected_conditions:
        raise RuntimeError("conditions do not match the frozen 3x3x2 Cartesian product")

    source_hashes: dict[str, str] = {}
    matrix: list[dict[str, Any]] = []
    seen: set[str] = set()
    for condition in conditions:
        if not isinstance(condition, dict):
            raise RuntimeError("condition must be an object")
        condition_id = condition.get("condition_id")
        if not isinstance(condition_id, str) or condition_id in seen:
            raise RuntimeError("condition ids must be unique strings")
        seen.add(condition_id)
        refs: list[str] = []
        for factor in ("ade", "harness", "agentskit"):
            component = condition.get(factor)
            declared = preflight.get(factor, {}).get(component, {})
            if not isinstance(component, str) or not isinstance(declared, dict) or declared.get("status") not in READY:
                raise RuntimeError(f"condition {condition_id} has an unready {factor}")
            component_refs = COMPONENT_EVIDENCE[factor].get(component)
            if component_refs is None:
                raise RuntimeError(f"condition {condition_id} has no frozen {factor} evidence")
            for ref in component_refs:
                validate_attestation(ref)
                refs.append(ref)
        invariant_evidence: dict[str, dict[str, Any]] = {}
        for invariant in INVARIANTS:
            invariant_refs = sorted(set(refs + list(GLOBAL_EVIDENCE[invariant]) + list(TOOLCHAIN_EVIDENCE)))
            for ref in invariant_refs:
                source_hashes.setdefault(ref, digest(ROOT / ref))
            invariant_evidence[invariant] = {"status": "precondition-verified", "evidence_refs": invariant_refs}
        matrix.append({
            "condition_id": condition_id,
            "factors": {factor: condition[factor] for factor in ("ade", "harness", "agentskit")},
            "invariants": invariant_evidence,
            "integration_evidence_ref": None,
            "verified": False,
        })

    document = {
        "schema_version": "semantic-parity-matrix-v1.1",
        "protocol_version": "v1.1",
        "generator": "controller/scripts/build_semantic_parity_matrix.py",
        "status": "preconditions-verified",
        "condition_count": len(matrix),
        "invariant_count": len(INVARIANTS),
        "precondition_verification_count": len(matrix) * len(INVARIANTS),
        "integration_verification_count": 0,
        "conditions_sha256": digest(args.conditions),
        "component_statuses": {
            factor: {key: value["status"] for key, value in sorted(preflight[factor].items())}
            for factor in ("ade", "harness", "agentskit")
        },
        "source_hashes": dict(sorted(source_hashes.items())),
        "conditions": matrix,
        "failure_policy": "Any missing component, evidence file, invariant, malformed condition, or hash mismatch blocks official collection.",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"status": "preconditions-verified", "conditions": len(matrix), "integration_verifications": 0}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
