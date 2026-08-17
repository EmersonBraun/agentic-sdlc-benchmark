#!/usr/bin/env python3
"""Run a provider-free AgentsKit observer probe into the benchmark ledger."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "controller" / "src"))

from benchmark_controller.agentskit import AgentsKitLedgerBridge  # noqa: E402
from benchmark_controller.ledger import Ledger  # noqa: E402


def _run_runtime_probe(core_dist: Path, node_path: str) -> list[dict[str, Any]]:
    module_path = json.dumps(str(core_dist.resolve()))
    script = f"""
import {{ pathToFileURL }} from 'node:url'
const {{ createChatController }} = await import(pathToFileURL({module_path}).href)

const events = []
const adapter = {{
  createSource: () => {{
    let aborted = false
    return {{
      stream: async function* () {{
        if (aborted) return
        yield {{ type: 'text', content: 'probe response' }}
        yield {{ type: 'usage', usage: {{ promptTokens: 2, completionTokens: 3, totalTokens: 5 }} }}
        yield {{ type: 'done' }}
      }},
      abort: () => {{ aborted = true }},
    }}
  }},
}}

const controller = createChatController({{
  adapter,
  observers: [{{ name: 'benchmark-ledger-probe', on: (event) => events.push(event) }}],
}})
await controller.send('probe input')
process.stdout.write(JSON.stringify(events))
"""
    result = subprocess.run(
        [node_path, "--input-type=module", "--eval", script],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        raise RuntimeError(f"AgentsKit runtime probe failed: {result.stderr.strip()}")
    events = json.loads(result.stdout)
    if not isinstance(events, list):
        raise RuntimeError("AgentsKit runtime probe did not return an event list")
    return events


def run_probe(core_dist: Path, node_path: str) -> dict[str, Any]:
    events = _run_runtime_probe(core_dist, node_path)
    with tempfile.TemporaryDirectory() as directory:
        ledger_path = Path(directory) / "ledger.jsonl"
        ledger = Ledger(ledger_path, run_id="run_agentskit_probe", task_id="pilot_smoke")
        bridge = AgentsKitLedgerBridge(ledger, enabled=True)
        ledger_events = [bridge.on_event(event) for event in events]
        ledger_text = ledger_path.read_text(encoding="utf-8")
        raw_content_redacted = "probe response" not in ledger_text and "probe input" not in ledger_text
        return {
            "observer_events": len(events),
            "observer_event_types": [event.get("type") for event in events],
            "ledger_events": len(ledger_events),
            "ledger_event_types": [event["event_type"] for event in ledger_events],
            "event_bridge": "live",
            "ledger_emission": "live" if ledger_events else "failed",
            "ledger_redaction": "live" if raw_content_redacted else "failed",
            "provider_called": False,
            "agent_session_started": False,
        }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--core-dist", type=Path, required=True)
    parser.add_argument("--node", default="node")
    args = parser.parse_args()
    print(json.dumps(run_probe(args.core_dist, args.node), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
