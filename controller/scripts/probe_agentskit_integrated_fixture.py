#!/usr/bin/env python3
"""Run one integrated, provider-free AgentsKit semantic-parity fixture."""

from __future__ import annotations

import argparse
import hashlib
import json
import tempfile
from pathlib import Path

from benchmark_controller.agentskit import AgentsKitLedgerBridge
from benchmark_controller.agentskit_components import AgentsKitComponentActionBridge
from benchmark_controller.ledger import Ledger
from probe_agentskit_components import _run_public_core


COMPONENT_ACTIONS = (
    {"component": "doc-bridge", "operation": "lookup", "phase": "start"},
    {"component": "doc-bridge", "operation": "lookup", "phase": "complete", "durationMs": 2},
    {"component": "playbook", "operation": "step", "phase": "complete", "step": 1},
    {"component": "specialized-agents", "operation": "delegate", "phase": "start", "name": "requirements"},
    {"component": "specialized-agents", "operation": "delegate", "phase": "complete", "name": "requirements", "durationMs": 3},
    {"component": "code-review", "operation": "review", "phase": "complete", "durationMs": 4},
)


def _fingerprint(events: list[dict[str, object]]) -> str:
    stable = [
        {
            key: event.get(key)
            for key in ("schema_version", "stage_id", "actor", "event_type", "parent_event_id", "tool", "status", "artifact_refs", "tokens")
        }
        for event in events
    ]
    return hashlib.sha256(json.dumps(stable, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    args = parser.parse_args()

    runtime = _run_public_core(args.source.resolve())
    with tempfile.TemporaryDirectory(prefix="agentic-sdlc-agentskit-integrated-") as directory:
        ledger_path = Path(directory) / "ledger.jsonl"
        ledger = Ledger(ledger_path, run_id="run_agentskit_integrated", task_id="pilot_integrated")
        event_bridge = AgentsKitLedgerBridge(ledger, enabled=True)
        action_bridge = AgentsKitComponentActionBridge(event_bridge)
        ledger_events = [event_bridge.on_event(event) for event in runtime["events"]]
        ledger_events.extend(action_bridge.record(action) for action in COMPONENT_ACTIONS)

    print(json.dumps({
        "schema_version": "agentskit-integrated-fixture-attestation-v1.0",
        "protocol_version": "v1.0",
        "source_scope": "local-public-AgentsKit-source",
        "provider_called": False,
        "agent_session_started": False,
        "core_runtime_event_count": len(runtime["events"]),
        "component_action_count": len(COMPONENT_ACTIONS),
        "ledger_event_count": len(ledger_events),
        "ledger_event_types": sorted({event["event_type"] for event in ledger_events}),
        "contract_fingerprint_sha256": _fingerprint(ledger_events),
        "raw_content_persisted": False,
        "decision": "The public core fixture and benchmark-side component actions share one redacted ledger without a provider or agent session. This proves provider-free semantic wiring only; it does not authorize pilot collection.",
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
