#!/usr/bin/env python3
"""Build the fail-closed v1.2 smoke matrix and preflight binding."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "controller/src"))

from benchmark_controller.v12_execution import V12_REQUIRED_SOURCE_REFS  # noqa: E402
from benchmark_controller.v12_integration import EXPECTED_CONDITIONS  # noqa: E402

MISSING_GATES = {
    "frozen_base_worktree", "full_sdlc", "complete_ade_ledger",
    "agentskit_inside_ade", "permission_parity", "independent_evaluation",
}
EXECUTED_PROBE_HASHES = {
    "agent-orchestrator": "41b7c106e864322a0111605cecb2168b3a2983a1ca016ff1a91306f0459f06fc",
    "compozy": "e37bda514a0ea3a0ca88c1d739d0aa9ab71ba9523f932b3fad7b92b21216c932",
    "orca": "8b00048644a3fcbdea8fc9b43a172dda1d3f2cce99534253c89d66d4a29914ea",
}


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _validate_smoke(path: Path, expected_condition: str) -> dict:
    document = json.loads(path.read_text())
    ade, factor = expected_condition.rsplit("__", 1)
    if not all((
        document.get("schema_version") == "condition-connectivity-smoke-attestation-v1.2",
        document.get("protocol_version") == "v1.2",
        document.get("analysis_eligible") is False,
        document.get("semantic_parity_eligible") is False,
        document.get("live_connectivity_execution") is True,
        document.get("status") == "passed",
        document.get("condition_id") == expected_condition,
        document.get("factors") == {"ade": ade, "agentskit": factor},
        set(document.get("missing_gates", [])) == MISSING_GATES,
        document.get("cleanup", {}).get("verified") is True,
    )):
        raise RuntimeError(f"invalid connectivity smoke: {path.name}")
    ledger = path.with_name(path.stem + "-ledger.jsonl")
    if not ledger.is_file() or _sha(ledger) != document.get("ledger_sha256"):
        raise RuntimeError(f"connectivity smoke ledger binding failed: {path.name}")
    revision = document.get("source_revision", {})
    probe_hash = document.get("source_hashes", {}).get("probe")
    if not all((
        probe_hash == EXECUTED_PROBE_HASHES[ade],
        revision.get("git_commit") == "55fd50270f11c5c9a7a69d6f2e9d9d1a3db85498",
        revision.get("probe_sha256_matches_commit") is True,
    )):
        raise RuntimeError(f"connectivity smoke source binding failed: {path.name}")
    topology = document.get("topology", {})
    planner = topology.get("planner", {})
    executor = topology.get("executor", {})
    if (
        planner.get("provider") not in {"codex", "codex-cli"}
        or planner.get("model") != "gpt-5.4"
        or executor.get("provider") not in {"grok-cli"}
        or executor.get("model", executor.get("configured_model")) != "grok-4.5"
    ):
        raise RuntimeError(f"connectivity smoke topology binding failed: {path.name}")
    if ade == "compozy":
        planner_run = planner.get("execution", {})
        executor_run = executor.get("execution", {})
        observed = all((
            planner_run.get("sentinel_observed"), planner_run.get("done_observed"),
            planner_run.get("providers") == ["codex"], planner_run.get("models") == ["gpt-5.4"],
            executor_run.get("sentinel_observed"), executor_run.get("done_observed"),
            executor_run.get("providers") == ["grok-cli"],
        ))
    elif ade == "orca":
        observed = all(
            all((
                settlement.get("status") == "completed", settlement.get("failure_count") == 0,
                settlement.get("capability_hash_present"), settlement.get("capability_revoked"),
                settlement.get("worker_done_accepted"), settlement.get("delivery_acknowledged"),
            ))
            for settlement in (planner.get("settlement", {}), executor.get("settlement", {}))
        )
    else:
        observed = all(
            all((
                execution.get("sentinel_observed"), execution.get("effective_model_observed"),
                execution.get("workspace_clean"), execution.get("trust_prompt_observed") is False,
            ))
            for execution in (planner.get("execution", {}), executor.get("execution", {}))
        )
    if not observed:
        raise RuntimeError(f"connectivity smoke execution observation failed: {path.name}")
    return document


def main() -> int:
    records = [
        ROOT / "adapters" / f"connectivity-smoke-{condition.replace('__', '-')}-v1.2.json"
        for condition in EXPECTED_CONDITIONS
    ]
    source_hashes = {
        reference: _sha(ROOT / reference)
        for reference in sorted(V12_REQUIRED_SOURCE_REFS)
    }
    smoke_conditions = []
    for path in records:
        expected = path.name.removeprefix("connectivity-smoke-").removesuffix("-v1.2.json")
        for ade in ("agent-orchestrator", "compozy", "orca"):
            if expected.startswith(ade + "-"):
                expected = ade + "__" + expected.removeprefix(ade + "-")
                break
        document = _validate_smoke(path, expected)
        smoke_conditions.append({
            "condition_id": document["condition_id"],
            "connectivity_smoke_passed": True,
            "verified": False,
            "evidence": path.name,
            "evidence_sha256": _sha(path),
            "missing_gates": document["missing_gates"],
        })
    matrix = {
        "schema_version": "semantic-parity-matrix-v1.2",
        "protocol_version": "v1.2",
        "status": "blocked",
        "analysis_eligible": False,
        "scope": "live connectivity smoke only; not condition integration or effect evidence",
        "conditions": sorted(smoke_conditions, key=lambda item: item["condition_id"]),
        "source_hashes": source_hashes,
        "generator": "controller/scripts/build_v12_integration_matrix.py",
    }
    matrix_path = ROOT / "adapters/semantic-parity-matrix-v1.2.json"
    matrix_path.write_text(json.dumps(matrix, indent=2, sort_keys=True) + "\n")

    conditions = sorted(EXPECTED_CONDITIONS)
    preflight = {
        "schema_version": "preflight-v1.2",
        "protocol_version": "v1.2",
        "status": "connectivity-smoke-ready",
        "technical_pilot_status": "blocked-full-runner-and-evidence-contract",
        "official_collection_status": "blocked-runner-not-implemented",
        "technical_pilot": {
            "allowed_conditions": conditions,
            "analysis_eligible": False,
            "completed_conditions": [],
            "completed_connectivity_smokes": conditions,
        },
        "ade": {
            key: {
                "status": "installed-not-ready",
                "technical_pilot_status": "installed-not-ready",
                "evidence": [
                    f"connectivity-smoke-{key}-{factor}-v1.2.json"
                    for factor in ("off", "on")
                ],
            }
            for key in ("orca", "agent-orchestrator", "compozy")
        },
        "agentskit": {
            "off": {
                "status": "installed-not-ready",
                "technical_pilot_status": "installed-not-ready",
                "evidence": {"neutral_control": "live-zero-event-verified"},
            },
            "on": {
                "status": "installed-not-ready",
                "technical_pilot_status": "installed-not-ready",
                "evidence": {
                    "public_only": True,
                    "agentskit_os_used": False,
                    "components": ["doc-bridge", "playbook", "code-review"],
                    "live_conditions": 3,
                },
            },
        },
        "v12_semantic_parity": {
            "status": "blocked",
            "matrix": matrix_path.name,
            "matrix_sha256": _sha(matrix_path),
        },
        "limitations": [
            "Connectivity smokes validate live CLI/ADE wiring only and are excluded from effect estimates.",
            "They do not validate frozen-base execution, full SDLC, ledger completeness, or AgentsKit use inside the ADE.",
            "Official collection remains blocked until the resumable v1.2 condition runner is implemented.",
            "The study is single-operator and currently runs on one personal local machine.",
        ],
    }
    preflight_path = ROOT / "adapters/preflight-v1.2.json"
    preflight_path.write_text(json.dumps(preflight, indent=2, sort_keys=True) + "\n")
    print(json.dumps({
        "status": preflight["status"],
        "conditions": len(matrix["conditions"]),
        "matrix_sha256": preflight["v12_semantic_parity"]["matrix_sha256"],
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
