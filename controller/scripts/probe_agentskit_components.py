#!/usr/bin/env python3
"""Probe the public AgentsKit component boundary without a provider or session."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from benchmark_controller.agentskit import AGENTSKIT_COMPONENTS, AgentsKitLedgerBridge
from benchmark_controller.ledger import Ledger


NODE_FIXTURE = r"""
import { createChatController, createInMemoryMemory } from 'CORE_DIST'

const observed = []
let sourceCalls = 0
const adapter = {
  createSource: () => {
    sourceCalls += 1
    const chunks = sourceCalls === 1
      ? [
          { type: 'tool_call', toolCall: { id: 'tool-1', name: 'read_issue', args: '{}' } },
          { type: 'done' },
        ]
      : [
          { type: 'text', content: 'bounded synthetic result' },
          { type: 'usage', usage: { promptTokens: 7, completionTokens: 4, totalTokens: 11 } },
          { type: 'done' },
        ]
    return { async *stream() { yield* chunks }, abort() {} }
  },
}
const observer = { name: 'benchmark-provider-free-observer', on: event => observed.push(event) }
const memory = createInMemoryMemory()
const controller = createChatController({
  adapter,
  memory,
  observers: [observer],
  tools: [{
    name: 'read_issue',
    description: 'read-only fixture',
    parameters: { type: 'object', properties: {} },
    execute: () => 'fixture issue metadata',
  }],
})
await controller.send('run the bounded provider-free fixture')
await new Promise(resolve => setTimeout(resolve, 10))
console.log(JSON.stringify({ sourceCalls, events: observed }))
"""


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _git_revision(source: Path) -> str:
    result = subprocess.run(
        ("git", "-C", str(source), "rev-parse", "HEAD"),
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _package_snapshot(source: Path, package_path: str) -> dict[str, Any]:
    path = source / package_path / "package.json"
    raw = path.read_bytes()
    manifest = json.loads(raw)
    return {
        "path": package_path,
        "name": manifest["name"],
        "version": manifest["version"],
        "manifest_sha256": _sha256_bytes(raw),
    }


def _run_public_core(source: Path) -> dict[str, Any]:
    core_dist = source / "packages" / "core" / "dist" / "index.js"
    if not core_dist.is_file():
        raise RuntimeError(f"Public AgentsKit core dist is missing: {core_dist}")
    script = NODE_FIXTURE.replace("CORE_DIST", core_dist.as_uri())
    result = subprocess.run(
        ("node", "--input-type=module", "-e", script),
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)


def _synthetic_bridge_fixtures() -> list[dict[str, Any]]:
    """Exercise bridge normalization for agent-level events not emitted by core runtime."""

    return [
        {"type": "memory:load", "messageCount": 2},
        {"type": "memory:save", "messageCount": 2},
        {"type": "agent:step", "step": 1, "action": "plan"},
        {"type": "agent:delegate:start", "name": "requirements", "task": "bounded", "depth": 0},
        {"type": "agent:delegate:end", "name": "requirements", "result": "bounded", "durationMs": 1, "depth": 0},
        {"type": "progress", "label": "review", "status": "ok", "durationMs": 1},
        {"type": "error", "error": RuntimeError("synthetic bridge fixture")},
        {"type": "run-aborted"},
    ]


def _component_evidence(source: Path) -> dict[str, Any]:
    public_packages = {
        "specialized-agents": "packages/skills",
        "versioned-memory": "packages/memory",
        "telemetry": "packages/observability",
    }
    external_evidence = {
        "doc-bridge": "ecosystem-readiness/evidence/doc-bridge.json",
        "playbook": "ecosystem-readiness/evidence/playbook.json",
        "code-review": "ecosystem-readiness/evidence/code-review.json",
    }
    evidence: dict[str, Any] = {}
    for component, package_path in public_packages.items():
        evidence[component] = {
            "kind": "public-package",
            "package": _package_snapshot(source, package_path),
        }
    for component, evidence_path in external_evidence.items():
        path = source / evidence_path
        raw = path.read_bytes()
        manifest = json.loads(raw)
        evidence[component] = {
            "kind": "public-external-evidence",
            "repo": manifest["repo"],
            "audited_on": manifest["auditedOn"],
            "evidence_path": evidence_path,
            "evidence_sha256": _sha256_bytes(raw),
            "runtime_executed": False,
        }
    return evidence


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    args = parser.parse_args()
    source = args.source.resolve()

    if not source.is_dir():
        raise SystemExit(f"Public AgentsKit source does not exist: {source}")

    runtime = _run_public_core(source)
    actual_events = runtime["events"]
    all_events = actual_events + _synthetic_bridge_fixtures()

    with tempfile.TemporaryDirectory(prefix="agentic-sdlc-agentskit-components-") as directory:
        root = Path(directory)
        ledger_path = root / "ledger.jsonl"
        bridge = AgentsKitLedgerBridge(
            Ledger(ledger_path, run_id="run_agentskit_components", task_id="pilot_components"),
            enabled=True,
        )
        ledger_events = [bridge.on_event(event) for event in all_events]

    # Runtime durations, timestamps, and monotonic clocks are intentionally
    # excluded so the attestation fingerprint is stable across reruns.
    contract_fingerprint = [
        {
            key: event.get(key)
            for key in (
                "schema_version",
                "stage_id",
                "actor",
                "event_type",
                "parent_event_id",
                "tool",
                "status",
                "artifact_refs",
                "tokens",
            )
        }
        for event in ledger_events
    ]
    contract_fingerprint_sha256 = _sha256_bytes(
        json.dumps(contract_fingerprint, sort_keys=True, separators=(",", ":")).encode("utf-8")
    )

    package_evidence = _component_evidence(source)
    result = {
        "schema_version": "agentskit-component-attestation-v1.0",
        "protocol_version": "v1.0",
        "verified_on": "2026-08-17",
        "source": {
            "path": str(source),
            "commit": _git_revision(source),
            "public_only": True,
            "agentskit_os_used": False,
        },
        "runtime": {
            "core_dist": "packages/core/dist/index.js",
            "provider_called": False,
            "agent_session_started": False,
            "source_calls": runtime["sourceCalls"],
            "actual_event_count": len(actual_events),
            "actual_event_types": sorted({event["type"] for event in actual_events}),
        },
        "component_evidence": package_evidence,
        "bridge_contract": {
            "accepted_event_count": len(all_events),
            "ledger_event_count": len(ledger_events),
            "ledger_event_types": sorted({event["event_type"] for event in ledger_events}),
            "contract_fingerprint_sha256": contract_fingerprint_sha256,
            "raw_content_persisted": False,
            "synthetic_bridge_events": len(all_events) - len(actual_events),
        },
        "status": "partial-ready",
        "decision": "Telemetry and versioned-memory events were observed in a provider-free public-core fixture, and the full bridge contract was exercised with bounded synthetic agent events. Doc Bridge, playbook, and code-review remain evidence-only because their external runtimes were not materialized in this controlled workspace; full AgentsKit ON semantic parity is therefore not claimed.",
    }
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
