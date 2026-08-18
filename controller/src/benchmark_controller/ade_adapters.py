"""ADE adapter registry over the shared lifecycle boundary."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .adapters import ADE_DESCRIPTORS, ComponentDescriptor
from .external import ControlledAdapter, LifecycleBridge
from .ledger import Ledger

READY_STATUSES = {"contract-ready", "installed-ready"}


@dataclass(frozen=True)
class ADERuntimeSpec:
    key: str
    descriptor: ComponentDescriptor
    session_entrypoint: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "descriptor": {
                **asdict(self.descriptor),
                "capabilities": sorted(self.descriptor.capabilities),
            },
            "session_entrypoint": self.session_entrypoint,
        }


ADE_RUNTIME_SPECS = {
    key: ADERuntimeSpec(key, descriptor, descriptor.entrypoint)
    for key, descriptor in ADE_DESCRIPTORS.items()
}


class ADENotReadyError(RuntimeError):
    """Raised when an ADE would otherwise orchestrate without a live adapter."""


class ADEAdapter:
    def __init__(self, spec: ADERuntimeSpec, runtime: ControlledAdapter, ledger: Ledger) -> None:
        self.spec = spec
        self.runtime = runtime
        self.lifecycle = LifecycleBridge(ledger, tool=spec.key)

    @property
    def descriptor(self) -> ComponentDescriptor:
        return self.spec.descriptor

    def assert_ready(self) -> None:
        if self.descriptor.implementation_status not in READY_STATUSES:
            raise ADENotReadyError(
                f"ADE {self.spec.key!r} is {self.descriptor.implementation_status}; no session started"
            )

    def record_lifecycle(
        self,
        *,
        stage_id: str,
        actor: str,
        status: str,
        duration_ms: float = 0,
        event_name: str = "stage",
    ) -> dict[str, object]:
        self.assert_ready()
        return self.lifecycle.record(
            stage_id=stage_id,
            actor=actor,
            status=status,
            duration_ms=duration_ms,
            event_name=event_name,
        )

    def record_blocked_attempt(
        self,
        *,
        stage_id: str,
        actor: str,
        event_name: str = "adapter.not-ready",
    ) -> dict[str, object]:
        return self.lifecycle.record(
            stage_id=stage_id,
            actor=actor,
            status="blocked",
            event_name=event_name,
        )

    def record_external_event(
        self,
        event: dict[str, object],
        *,
        stage_id: str,
        actor: str,
        parent_event_id: str | None = None,
    ) -> dict[str, object]:
        self.assert_ready()
        return self.lifecycle.record_external(
            event,
            stage_id=stage_id,
            actor=actor,
            parent_event_id=parent_event_id,
        )


def build_ade_adapter(
    key: str,
    workspace: Path,
    ledger: Ledger,
    *,
    permission_mode: str,
) -> Any:
    try:
        spec = ADE_RUNTIME_SPECS[key]
    except KeyError as exc:
        raise ValueError(f"Unknown ADE adapter: {key!r}") from exc
    if key == "orca":
        from .orca import OrcaAdapter

        return OrcaAdapter(workspace, ledger, permission_mode=permission_mode)
    runtime = ControlledAdapter(workspace, ledger, permission_mode=permission_mode)  # type: ignore[arg-type]
    return ADEAdapter(spec, runtime, ledger)
