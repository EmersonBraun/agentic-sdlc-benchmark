"""Container-bound mini-SWE-agent adapter with a side-effect-free preflight."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .adapters import ComponentDescriptor, HARNESS_DESCRIPTORS
from .external import ControlledAdapter
from .ledger import Ledger

DEFAULT_DOCKER_CLI = "docker"
DEFAULT_IMAGE = "agentic-sdlc-mini-swe-agent:2.4.6"
READY_STATUSES = {"contract-ready", "installed-ready"}


@dataclass(frozen=True)
class MiniSwePreflight:
    image: dict[str, Any]
    help_probe: dict[str, Any]
    workspace_probe: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "image": self.image,
            "help_probe": self.help_probe,
            "workspace_probe": self.workspace_probe,
            "agent_sessions_started": False,
            "workspace_mounted": self.workspace_probe["passed"],
            "network_enabled": False,
            "permission_parity": "contract-tested" if self.workspace_probe["permission_mode"] == "approve-reads" else "failed",
            "ledger_bridge": "live",
        }


class MiniSweNotReadyError(RuntimeError):
    """Raised before task execution when the harness is not collection-ready."""


class MiniSweAgentAdapter:
    """Run only the pinned mini-SWE-agent container boundary until readiness is complete."""

    def __init__(
        self,
        workspace: Path,
        ledger: Ledger,
        *,
        permission_mode: str = "approve-reads",
        docker_path: str = DEFAULT_DOCKER_CLI,
        image: str = DEFAULT_IMAGE,
    ) -> None:
        self.descriptor: ComponentDescriptor = HARNESS_DESCRIPTORS["mini-swe-agent"]
        self.runtime = ControlledAdapter(workspace, ledger, permission_mode=permission_mode)  # type: ignore[arg-type]
        self.docker_path = docker_path
        self.image = image

    def read_only_preflight(self) -> MiniSwePreflight:
        """Inspect the image and CLI with no network and no mounted workspace."""

        image_result = self.runtime.run(
            (self.docker_path, "image", "inspect", self.image, "--format", "{{.Id}}"),
            stage_id="intake",
            actor="infrastructure",
            access="read",
            time_category="orchestration_overhead",
        )
        help_result = self.runtime.run(
            self._container_command("--help"),
            stage_id="intake",
            actor="infrastructure",
            access="read",
            time_category="orchestration_overhead",
        )
        workspace_result = self.runtime.run(
            self._workspace_probe_command(),
            stage_id="intake",
            actor="infrastructure",
            access="read",
            time_category="orchestration_overhead",
            env={"BENCHMARK_PERMISSION_MODE": self.runtime.permissions.mode},
        )
        image_id = image_result.stdout.strip() if image_result.returncode == 0 else None
        workspace_passed = workspace_result.returncode == 0 and "mini-swe workspace boundary ok" in workspace_result.stdout
        return MiniSwePreflight(
            image={"image": self.image, "image_id": image_id, "inspect_passed": image_result.returncode == 0},
            help_probe={
                "returncode": help_result.returncode,
                "passed": help_result.returncode == 0 and "mini-swe-agent version 2.4.6" in help_result.stdout,
                "version": "2.4.6" if "mini-swe-agent version 2.4.6" in help_result.stdout else None,
                "network_enabled": False,
                "workspace_mounted": False,
            },
            workspace_probe={
                "returncode": workspace_result.returncode,
                "passed": workspace_passed,
                "permission_mode": self.runtime.permissions.mode,
                "network_enabled": False,
                "mount_read_only": True,
            },
        )

    def run_task(self, *, issue_text: str) -> dict[str, Any]:
        self._assert_ready()
        if not issue_text:
            raise ValueError("issue_text must be non-empty")
        raise NotImplementedError("Live mini-SWE-agent task execution is intentionally not enabled in this stage")

    def _assert_ready(self) -> None:
        if self.descriptor.implementation_status not in READY_STATUSES:
            raise MiniSweNotReadyError(
                f"mini-SWE-agent is {self.descriptor.implementation_status}; no task session started"
            )

    def _container_command(self, argument: str) -> tuple[str, ...]:
        return self._base_container_command() + (argument,)

    def _workspace_probe_command(self) -> tuple[str, ...]:
        probe = (
            "from pathlib import Path; import os; "
            "assert Path('/workspace').is_dir(); "
            "assert os.environ.get('BENCHMARK_PERMISSION_MODE') == 'approve-reads'; "
            "print('mini-swe workspace boundary ok')"
        )
        return self._base_container_command(mount_workspace=True, entrypoint="python3") + ("-c", probe)

    def _base_container_command(
        self,
        *,
        mount_workspace: bool = False,
        entrypoint: str | None = None,
    ) -> tuple[str, ...]:
        command = (
            self.docker_path,
            "run",
            "--rm",
            "--network",
            "none",
            "--read-only",
            "--tmpfs",
            "/tmp:rw,nosuid,nodev,noexec,size=64m",
            "--cap-drop=ALL",
            "--security-opt=no-new-privileges",
            "--env",
            "HOME=/tmp",
            "--env",
            f"BENCHMARK_PERMISSION_MODE={self.runtime.permissions.mode}",
        )
        if entrypoint:
            command += ("--entrypoint", entrypoint)
        command += (self.image,)
        if mount_workspace:
            command = command[:-1] + (
                "--mount",
                f"type=bind,src={self.runtime.workspace},dst=/workspace,readonly",
                self.image,
            )
        return command
