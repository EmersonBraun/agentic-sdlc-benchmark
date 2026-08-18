"""Operational readiness report for resuming the frozen v1.1 study."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping

from .readiness import READY_STATUSES
from .semantic_parity import REQUIRED_EVIDENCE_KEYS, evaluate_semantic_parity


@dataclass(frozen=True)
class ExecutionBlocker:
    blocker_id: str
    component: str
    owner: str
    reason: str
    evidence_ref: str
    next_action: str
    recheck_command: str


@dataclass(frozen=True)
class ExecutionReadinessReport:
    schema_version: str
    protocol_version: str
    can_start_official_collection: bool
    official_conditions_ready: int
    official_conditions_total: int
    technical_conditions_ready: tuple[str, ...]
    blockers: tuple[ExecutionBlocker, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "protocol_version": self.protocol_version,
            "can_start_official_collection": self.can_start_official_collection,
            "official_conditions_ready": self.official_conditions_ready,
            "official_conditions_total": self.official_conditions_total,
            "technical_conditions_ready": list(self.technical_conditions_ready),
            "blocker_summary": {
                owner: sum(blocker.owner == owner for blocker in self.blockers)
                for owner in ("operator", "upstream", "protocol")
            },
            "blockers": [asdict(blocker) for blocker in self.blockers],
        }


BLOCKER_SPECS: dict[str, ExecutionBlocker] = {
    "ade:orca": ExecutionBlocker(
        "orca-dispatch-capability", "ade:orca", "upstream",
        "gpt-5.4 executes, but authoritative worker_done is rejected with dispatch_capability_invalid.",
        "adapters/orca-v1.1-lifecycle-probe-attestation-4.json",
        "Install an ORCA runtime that supplies a valid Dispatch capability, then require one accepted worker_done and complete release.",
        "orca status --json",
    ),
    "ade:agent-orchestrator": ExecutionBlocker(
        "ao-observability", "ade:agent-orchestrator", "upstream",
        "The public CLI starts and cleans sessions but exposes neither model output nor a native event stream.",
        "adapters/agent-orchestrator-v1.1-session-probe-attestation.json",
        "Recheck a release that exposes independently observable model execution and lifecycle events.",
        "PYTHONPATH=controller/src python3 controller/scripts/probe_agent_orchestrator_lifecycle.py",
    ),
    "ade:compozy": ExecutionBlocker(
        "compozy-runtime-parity", "ade:compozy", "protocol",
        "The Compozy runtime has not independently satisfied its declared workspace, model, lifecycle, ledger, and cleanup contract.",
        "adapters/compozy-v1.1-component-readiness-attestation.json",
        "Repeat the isolated provider-backed lifecycle probe and require every component-local invariant to pass.",
        "PYTHONPATH=controller/src python3 controller/scripts/probe_compozy_session.py --confirm",
    ),
    "harness:openhands-sdk": ExecutionBlocker(
        "openhands-dependency-graph", "harness:openhands-sdk", "upstream",
        "The latest approved SDK dependency graph does not resolve on pinned Python without overrides.",
        "adapters/openhands-resolver-attestation-v1.0.json",
        "Re-run the normal resolver when a compatible OpenHands release is published; do not use dependency overrides.",
        "docker run --rm python:3.12.10-slim python -m pip install --dry-run --no-cache-dir openhands-sdk==1.42.1 openhands-tools==1.42.1 openhands-workspace==1.42.1",
    ),
    "harness:mini-swe-agent": ExecutionBlocker(
        "mini-swe-cli-transport", "harness:mini-swe-agent", "protocol",
        "The isolated runtime requires successful model and task execution through the frozen native CLI transport.",
        "adapters/mini-swe-cli-bridge-attestation-v1.1.json",
        "Run the bounded greenfield and brownfield CLI bridge probes and require tests, ledger, submission, and cleanup.",
        "PYTHONPATH=controller/src pipx run --spec mini-swe-agent==2.4.6 python controller/scripts/probe_mini_swe_cli_bridge.py",
    ),
    "harness:reference": ExecutionBlocker(
        "reference-harness-contract", "harness:reference", "protocol",
        "The neutral reference harness is missing or no longer contract-ready.",
        "adapters/preflight-v1.1.json",
        "Restore and validate the frozen reference-harness contract before collecting official runs.",
        "PYTHONPATH=controller/src python3 controller/scripts/check_pilot_gate.py --preflight adapters/preflight-v1.1.json --gate-mode official-collection",
    ),
    "agentskit:off": ExecutionBlocker(
        "agentskit-off-control", "agentskit:off", "protocol",
        "The neutral AgentsKit OFF control is missing or no longer contract-ready.",
        "adapters/agentskit-v1.1-preflight-attestation.json",
        "Restore the frozen OFF control before collecting any matched AgentsKit ON condition.",
        "PYTHONPATH=controller/src python3 controller/scripts/check_pilot_gate.py --preflight adapters/preflight-v1.1.json --gate-mode official-collection",
    ),
    "agentskit:on": ExecutionBlocker(
        "agentskit-component-parity", "agentskit:on", "protocol",
        "AgentsKit ON has not independently proved public-only execution, ledger mapping, redaction, and a provider-backed matched OFF control.",
        "adapters/agentskit-v1.1-component-readiness-attestation.json",
        "Repeat the controlled public-component probes and matched provider-backed ON/OFF task.",
        "PYTHONPATH=controller/src:controller/scripts python3 controller/scripts/probe_agentskit_integrated_fixture.py --source /path/to/pinned/public/agentskit",
    ),
}

GLOBAL_PARITY_BLOCKER = ExecutionBlocker(
    "global-semantic-parity",
    "protocol:semantic-parity",
    "protocol",
    "Component-local readiness is incomplete across the full 18-condition matrix.",
    "adapters/semantic-parity-v1.0.json",
    "Close every component-local blocker, verify all seven invariants for 18/18 conditions, then promote the global gate.",
    "PYTHONPATH=controller/src python3 controller/scripts/check_pilot_gate.py --preflight adapters/preflight-v1.1.json --gate-mode official-collection",
)


def evaluate_execution_readiness(preflight: Mapping[str, Any]) -> ExecutionReadinessReport:
    if preflight.get("protocol_version") != "v1.1":
        raise ValueError("Execution readiness requires protocol v1.1")

    blockers: list[ExecutionBlocker] = []
    for component, spec in BLOCKER_SPECS.items():
        factor, key = component.split(":", 1)
        document = preflight.get(factor, {}).get(key, {})
        if not isinstance(document, Mapping) or document.get("status") not in READY_STATUSES:
            blockers.append(spec)

    if not evaluate_semantic_parity(preflight).verified:
        blockers.append(GLOBAL_PARITY_BLOCKER)

    technical = preflight.get("technical_pilot", {}).get("allowed_conditions", [])
    technical_ready = tuple(sorted(str(value) for value in technical)) if isinstance(technical, list) else ()
    return ExecutionReadinessReport(
        schema_version="execution-readiness-v1.1",
        protocol_version="v1.1",
        can_start_official_collection=not blockers,
        official_conditions_ready=18 if not blockers else 0,
        official_conditions_total=18,
        technical_conditions_ready=technical_ready,
        blockers=tuple(blockers),
    )
