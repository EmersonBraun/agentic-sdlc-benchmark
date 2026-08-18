"""Harness adapter registry over the shared controlled runtime boundary."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from .adapters import HARNESS_DESCRIPTORS, ComponentDescriptor
from .external import AccessType, AdapterCommandResult, ControlledAdapter
from .ledger import Ledger

READY_STATUSES = {"contract-ready", "installed-ready"}


@dataclass(frozen=True)
class HarnessRuntimeSpec:
    key: str
    descriptor: ComponentDescriptor
    runtime_image: str | None = None
    session_entrypoint: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "descriptor": {
                **asdict(self.descriptor),
                "capabilities": sorted(self.descriptor.capabilities),
            },
            "runtime_image": self.runtime_image,
            "session_entrypoint": self.session_entrypoint,
        }


HARNESS_RUNTIME_SPECS = {
    "reference": HarnessRuntimeSpec(
        "reference", HARNESS_DESCRIPTORS["reference"], session_entrypoint="controller:reference-harness"
    ),
    "openhands-sdk": HarnessRuntimeSpec(
        "openhands-sdk",
        HARNESS_DESCRIPTORS["openhands-sdk"],
        runtime_image="ghcr.io/astral-sh/uv:python3.12-bookworm-slim@sha256:e5b65587bce7de595f299855d7385fe7fca39b8a74baa261ba1b7147afa78e58",
        session_entrypoint="controller/scripts/probe_openhands_sdk.py",
    ),
    "mini-swe-agent": HarnessRuntimeSpec(
        "mini-swe-agent",
        HARNESS_DESCRIPTORS["mini-swe-agent"],
        runtime_image="product-snapshot-selected",
        session_entrypoint="controller/scripts/probe_mini_swe_cli_bridge.py",
    ),
}


class HarnessNotReadyError(RuntimeError):
    """Raised when a harness would otherwise run without a live adapter."""


class HarnessAdapter:
    def __init__(self, spec: HarnessRuntimeSpec, runtime: ControlledAdapter) -> None:
        self.spec = spec
        self.runtime = runtime

    @property
    def descriptor(self) -> ComponentDescriptor:
        return self.spec.descriptor

    def assert_ready(self) -> None:
        if self.descriptor.implementation_status not in READY_STATUSES:
            raise HarnessNotReadyError(
                f"Harness {self.spec.key!r} is {self.descriptor.implementation_status}; no session started"
            )

    def run_command(
        self,
        command: Sequence[str],
        *,
        stage_id: str,
        actor: str,
        access: AccessType,
        time_category: str = "effective_work",
        timeout_seconds: float = 120,
        env: Mapping[str, str] | None = None,
    ) -> AdapterCommandResult:
        self.assert_ready()
        return self.runtime.run(
            command,
            stage_id=stage_id,
            actor=actor,
            access=access,
            time_category=time_category,
            timeout_seconds=timeout_seconds,
            env=env,
        )


def build_harness_adapter(
    key: str,
    workspace: Path,
    ledger: Ledger,
    *,
    permission_mode: str,
) -> Any:
    try:
        spec = HARNESS_RUNTIME_SPECS[key]
    except KeyError as exc:
        raise ValueError(f"Unknown harness adapter: {key!r}") from exc
    if key == "mini-swe-agent":
        from .mini_swe import MiniSweAgentAdapter

        return MiniSweAgentAdapter(
            workspace,
            ledger,
            permission_mode=permission_mode,
        )
    return HarnessAdapter(
        spec,
        ControlledAdapter(workspace, ledger, permission_mode=permission_mode),  # type: ignore[arg-type]
    )
