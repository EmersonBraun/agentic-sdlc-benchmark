"""Deterministic semantic-readiness evaluation for frozen adapter preflight."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping

READY_STATUSES = frozenset({"contract-ready", "installed-ready"})
FACTORS = frozenset({"ade", "harness", "agentskit"})


@dataclass(frozen=True)
class ReadinessCheck:
    check_id: str
    passed: bool
    evidence: str


@dataclass(frozen=True)
class ComponentReadiness:
    factor: str
    key: str
    status: str
    ready: bool
    checks: tuple[ReadinessCheck, ...]
    blockers: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "factor": self.factor,
            "key": self.key,
            "status": self.status,
            "ready": self.ready,
            "checks": [asdict(check) for check in self.checks],
            "blockers": list(self.blockers),
        }


@dataclass(frozen=True)
class ReadinessReport:
    protocol_version: str
    ready_components: int
    blocked_components: int
    components: tuple[ComponentReadiness, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "protocol_version": self.protocol_version,
            "ready_components": self.ready_components,
            "blocked_components": self.blocked_components,
            "components": [component.to_dict() for component in self.components],
        }


def evaluate_adapter_readiness(preflight: Mapping[str, Any]) -> ReadinessReport:
    protocol_version = str(preflight.get("protocol_version", ""))
    if protocol_version not in {"v1.0", "v1.1"}:
        raise ValueError("Readiness preflight must target a supported protocol version")

    components: list[ComponentReadiness] = []
    for factor in ("ade", "harness", "agentskit"):
        documents = preflight.get(factor, {})
        if not isinstance(documents, Mapping):
            raise ValueError(f"Preflight factor {factor!r} must be an object")
        for key, document in documents.items():
            if not isinstance(document, Mapping):
                raise ValueError(f"Preflight component {factor}:{key} must be an object")
            components.append(_evaluate_component(factor, str(key), document))

    ready = sum(component.ready for component in components)
    return ReadinessReport(
        protocol_version=protocol_version,
        ready_components=ready,
        blocked_components=len(components) - ready,
        components=tuple(sorted(components, key=lambda component: (component.factor, component.key))),
    )


def _evaluate_component(factor: str, key: str, document: Mapping[str, Any]) -> ComponentReadiness:
    status = str(document.get("status", "missing"))
    evidence = document.get("evidence", {})
    if not isinstance(evidence, Mapping):
        evidence = {}

    checks: list[ReadinessCheck] = [
        ReadinessCheck(
            "implementation-status",
            status in READY_STATUSES,
            f"status={status}",
        )
    ]
    if factor == "ade":
        checks.extend(
            [
                _check("health", _has_any(evidence, "doctor_core", "runtime_reachable", "daemon_status"), evidence),
                _check("workspace", _has_any(evidence, "registered_project", "registered_workspace_id"), evidence),
                _check("permissions", _has_any(evidence, "global_permission_mode", "permission_mode"), evidence),
                _check("lifecycle-bridge", _has_any(evidence, "lifecycle_bridge", "adapter_lifecycle"), evidence),
                _check("ledger-bridge", _has_any(evidence, "ledger_bridge", "event_bridge"), evidence),
            ]
        )
    elif factor == "harness":
        checks.extend(
            [
                _check("runtime", bool(document.get("installed")) or status == "contract-ready", document),
                _check("workspace-boundary", status == "contract-ready" or _has_any(evidence, "workspace_boundary"), evidence),
                _check("permission-parity", status == "contract-ready" or _has_any(evidence, "permission_parity"), evidence),
                _check("ledger-bridge", status == "contract-ready" or _has_any(evidence, "ledger_bridge"), evidence),
            ]
        )
    elif factor == "agentskit":
        if key == "off":
            checks.append(ReadinessCheck("neutral-control", status == "contract-ready", f"status={status}"))
        else:
            checks.extend(
                [
                    _check("cli", _has_any(evidence, "agentskit_help"), evidence),
                    _check("event-bridge", evidence.get("event_bridge") in {"contract-tested", "live"}, evidence),
                    _check("redaction", evidence.get("ledger_redaction") in {"contract-tested", "live"}, evidence),
                    _check("live-ledger", evidence.get("ledger_emission") == "live", evidence),
                ]
            )
    else:
        raise ValueError(f"Unknown readiness factor: {factor!r}")

    blockers = tuple(check.check_id for check in checks if not check.passed)
    return ComponentReadiness(factor, key, status, not blockers, tuple(checks), blockers)


def _has_any(document: Mapping[str, Any], *keys: str) -> bool:
    return any(key in document and document[key] not in (None, False, "", [], {}) for key in keys)


def _check(check_id: str, passed: bool, document: Mapping[str, Any]) -> ReadinessCheck:
    evidence_keys = sorted(str(key) for key in document if key != "doctor_errors")
    evidence = "present" if passed else f"missing; available={evidence_keys}"
    return ReadinessCheck(check_id, passed, evidence)
