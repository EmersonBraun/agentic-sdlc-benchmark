#!/usr/bin/env python3
"""Build the canonical v1.2 technical integration matrix and preflight binding."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "controller/src"))

from benchmark_controller.v12_execution import V12_REQUIRED_SOURCE_REFS  # noqa: E402
from benchmark_controller.v12_integration import EXPECTED_CONDITIONS, build_verified_matrix  # noqa: E402


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    records = [
        ROOT / "adapters" / f"condition-integration-{condition.replace('__', '-')}-v1.2.json"
        for condition in EXPECTED_CONDITIONS
    ]
    source_hashes = {
        reference: _sha(ROOT / reference)
        for reference in sorted(V12_REQUIRED_SOURCE_REFS)
    }
    matrix = build_verified_matrix(records, source_hashes)
    matrix["generator"] = "controller/scripts/build_v12_integration_matrix.py"
    matrix_path = ROOT / "adapters/semantic-parity-matrix-v1.2.json"
    matrix_path.write_text(json.dumps(matrix, indent=2, sort_keys=True) + "\n")

    conditions = sorted(EXPECTED_CONDITIONS)
    preflight = {
        "schema_version": "preflight-v1.2",
        "protocol_version": "v1.2",
        "status": "technical-pilot-ready",
        "official_collection_status": "blocked-runner-not-implemented",
        "technical_pilot": {
            "allowed_conditions": conditions,
            "analysis_eligible": False,
            "completed_conditions": conditions,
        },
        "ade": {
            key: {
                "status": "installed-not-ready",
                "technical_pilot_status": "installed-ready",
                "evidence": [
                    f"condition-integration-{key}-{factor}-v1.2.json"
                    for factor in ("off", "on")
                ],
            }
            for key in ("orca", "agent-orchestrator", "compozy")
        },
        "agentskit": {
            "off": {
                "status": "installed-not-ready",
                "technical_pilot_status": "contract-ready",
                "evidence": {"neutral_control": "live-zero-event-verified"},
            },
            "on": {
                "status": "installed-not-ready",
                "technical_pilot_status": "installed-ready",
                "evidence": {
                    "public_only": True,
                    "agentskit_os_used": False,
                    "components": ["doc-bridge", "playbook", "code-review"],
                    "live_conditions": 3,
                },
            },
        },
        "v12_semantic_parity": {
            "status": "verified",
            "matrix": matrix_path.name,
            "matrix_sha256": _sha(matrix_path),
        },
        "limitations": [
            "Technical bootstrap runs validate integration and are excluded from effect estimates.",
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
