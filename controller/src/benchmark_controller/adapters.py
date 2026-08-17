"""Declarative adapter contracts for the protocol-v1.0 condition matrix.

This module intentionally does not invoke external ADEs or harnesses. It builds
an immutable execution plan and refuses to substitute an unavailable adapter.
Live integrations are added behind the same contract in a later step.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Literal

from .conditions import EXPECTED_ADE, EXPECTED_AGENTSKIT, EXPECTED_HARNESSES
from .ids import validate_id

AdapterKind = Literal["ade", "harness", "agentskit"]

COMMON_HARNESS_CAPABILITIES = frozenset(
    {
        "workspace",
        "shell",
        "git",
        "github",
        "browser",
        "oracle",
        "permissions",
        "context",
        "ledger",
    }
)


@dataclass(frozen=True)
class ComponentDescriptor:
    kind: AdapterKind
    key: str
    adapter_version: str
    implementation_status: str
    entrypoint: str
    capabilities: frozenset[str]


@dataclass(frozen=True)
class ExecutionPlan:
    """The only input shape accepted by the future run executor."""

    run_id: str
    protocol_version: str
    ade: ComponentDescriptor
    harness: ComponentDescriptor
    agentskit: ComponentDescriptor
    semantic_parity: bool
    fallback_used: bool = False

    def to_dict(self) -> dict[str, object]:
        return {
            "run_id": self.run_id,
            "protocol_version": self.protocol_version,
            "ade": _descriptor_dict(self.ade),
            "harness": _descriptor_dict(self.harness),
            "agentskit": _descriptor_dict(self.agentskit),
            "semantic_parity": self.semantic_parity,
            "fallback_used": self.fallback_used,
        }


def _descriptor_dict(descriptor: ComponentDescriptor) -> dict[str, object]:
    result = asdict(descriptor)
    result["capabilities"] = sorted(descriptor.capabilities)
    return result


def _ade_descriptors() -> dict[str, ComponentDescriptor]:
    lifecycle = frozenset(
        {
            "requirements",
            "planning",
            "decomposition",
            "implementation",
            "testing",
            "review",
            "merge",
            "memory-update",
        }
    )
    return {
        "orca": ComponentDescriptor(
            "ade", "orca", "orca-runtime-1.4.183", "installed-not-ready", "external:orca", lifecycle
        ),
        "agent-orchestrator": ComponentDescriptor(
            "ade",
            "agent-orchestrator",
            "agent-orchestrator-0.12.6",
            "installed-not-ready",
            "external:agent-orchestrator",
            lifecycle,
        ),
        "compozy": ComponentDescriptor(
            "ade", "compozy", "compozy-0.3.0-beta.16", "installed-not-ready", "external:compozy", lifecycle
        ),
    }


def _harness_descriptors() -> dict[str, ComponentDescriptor]:
    return {
        "reference": ComponentDescriptor(
            "harness",
            "reference",
            "reference-harness-v1.0",
            "contract-ready",
            "controller:reference-harness",
            COMMON_HARNESS_CAPABILITIES,
        ),
        "openhands-sdk": ComponentDescriptor(
            "harness",
            "openhands-sdk",
            "openhands-sdk-1.42.1",
            "dependency-resolution-failed",
            "external:openhands-sdk",
            COMMON_HARNESS_CAPABILITIES,
        ),
        "mini-swe-agent": ComponentDescriptor(
            "harness",
            "mini-swe-agent",
            "mini-swe-agent-2.4.6",
            "installed-not-ready",
            "external:mini-swe-agent",
            COMMON_HARNESS_CAPABILITIES,
        ),
    }


def _agentskit_descriptors() -> dict[str, ComponentDescriptor]:
    on_capabilities = frozenset(
        {
            "doc-bridge",
            "playbook",
            "specialized-agents",
            "code-review",
            "versioned-memory",
            "telemetry",
        }
    )
    off_capabilities = frozenset(f"neutral-{name}" for name in on_capabilities)
    return {
        "on": ComponentDescriptor(
            "agentskit", "on", "agentskit-0.3.0-private-component-removed-local", "installed-not-ready", "external:agentskit", on_capabilities
        ),
        "off": ComponentDescriptor(
            "agentskit", "off", "neutral-control-v1.0", "contract-ready", "controller:neutral-control", off_capabilities
        ),
    }


ADE_DESCRIPTORS = _ade_descriptors()
HARNESS_DESCRIPTORS = _harness_descriptors()
AGENTSKIT_DESCRIPTORS = _agentskit_descriptors()


def build_execution_plan(*, run_id: str, ade: str, harness: str, agentskit: str) -> ExecutionPlan:
    """Resolve a condition without changing any factor or using a fallback."""

    validate_id(run_id, "run")
    if ade not in EXPECTED_ADE:
        raise ValueError(f"Unknown ADE adapter: {ade!r}")
    if harness not in EXPECTED_HARNESSES:
        raise ValueError(f"Unknown harness adapter: {harness!r}")
    if agentskit not in EXPECTED_AGENTSKIT:
        raise ValueError(f"Unknown AgentsKit factor: {agentskit!r}")

    ade_descriptor = ADE_DESCRIPTORS[ade]
    harness_descriptor = HARNESS_DESCRIPTORS[harness]
    agentskit_descriptor = AGENTSKIT_DESCRIPTORS[agentskit]
    semantic_parity = harness_descriptor.capabilities == COMMON_HARNESS_CAPABILITIES
    return ExecutionPlan(
        run_id=run_id,
        protocol_version="v1.0",
        ade=ade_descriptor,
        harness=harness_descriptor,
        agentskit=agentskit_descriptor,
        semantic_parity=semantic_parity,
    )


def assert_live_adapter_ready(plan: ExecutionPlan) -> None:
    """Fail closed until an external adapter has passed its installation gate."""

    unavailable = [
        descriptor.key
        for descriptor in (plan.ade, plan.harness, plan.agentskit)
        if descriptor.implementation_status not in {"contract-ready", "installed-ready"}
    ]
    if unavailable:
        raise RuntimeError(
            "Live adapter integration is not ready for: "
            + ", ".join(unavailable)
            + ". The controller will not substitute another adapter."
        )
