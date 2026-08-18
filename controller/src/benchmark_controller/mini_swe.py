"""Container-bound mini-SWE-agent adapter with a side-effect-free preflight."""

from __future__ import annotations

import json
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .adapters import ComponentDescriptor, HARNESS_DESCRIPTORS
from .external import ControlledAdapter
from .ledger import Ledger

DEFAULT_DOCKER_CLI = "docker"
DEFAULT_IMAGE = "agentic-sdlc-mini-swe-agent:2.4.6"
DEFAULT_EXECUTOR_IMAGE = "agentic-sdlc-greenfield:preflight-v1.0"
DEFAULT_EXECUTOR_IMAGE_ID = "sha256:437f9f730d5aeae089461f4949504277637ca1b72b769449d7ebc62402497a1a"
READY_STATUSES = {"contract-ready", "installed-ready"}


@dataclass(frozen=True)
class MiniSwePreflight:
    image: dict[str, Any]
    help_probe: dict[str, Any]
    workspace_probe: dict[str, Any]
    model_probe: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "image": self.image,
            "help_probe": self.help_probe,
            "workspace_probe": self.workspace_probe,
            "model_probe": self.model_probe,
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
        executor_image: str = DEFAULT_EXECUTOR_IMAGE,
        executor_image_id: str = DEFAULT_EXECUTOR_IMAGE_ID,
        interpreter: str = "bash",
        test_command: str = "./node_modules/.bin/vitest run",
    ) -> None:
        self.descriptor: ComponentDescriptor = HARNESS_DESCRIPTORS["mini-swe-agent"]
        self.runtime = ControlledAdapter(workspace, ledger, permission_mode=permission_mode)  # type: ignore[arg-type]
        self.docker_path = docker_path
        self.image = image
        self.executor_image = executor_image
        self.executor_image_id = executor_image_id
        self.interpreter = interpreter
        self.test_command = test_command

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
        model_result = self.runtime.run(
            self._model_probe_command(),
            stage_id="intake",
            actor="infrastructure",
            access="read",
            time_category="orchestration_overhead",
        )
        image_id = image_result.stdout.strip() if image_result.returncode == 0 else None
        workspace_passed = workspace_result.returncode == 0 and "mini-swe workspace boundary ok" in workspace_result.stdout
        model_fail_closed = model_result.returncode == 1 and "Aborted." in (model_result.stdout + model_result.stderr)
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
            model_probe={
                "returncode": model_result.returncode,
                "fail_closed": model_fail_closed,
                "task_argument_accepted": "No such option: --task" not in model_result.stderr,
                "network_enabled": False,
                "agent_session_started": False,
            },
        )

    def run_task(self, *, issue_text: str) -> dict[str, Any]:
        self.assert_ready()
        if not issue_text:
            raise ValueError("issue_text must be non-empty")
        if self.runtime.permissions.mode != "approve-all":
            raise PermissionError("Live mini-SWE-agent execution requires approve-all permission accounting")
        script = Path(__file__).resolve().parents[2] / "scripts" / "probe_mini_swe_cli_bridge.py"
        task_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                prefix="agentic-sdlc-mini-swe-task-",
                suffix=".md",
                dir="/private/tmp",
                delete=False,
            ) as stream:
                stream.write(issue_text)
                task_path = Path(stream.name)
            result = self.runtime.run(
                (
                    "pipx",
                    "run",
                    "--spec",
                    "mini-swe-agent==2.4.6",
                    "python",
                    str(script),
                    "--workspace",
                    str(self.runtime.workspace),
                    "--task-file",
                    str(task_path),
                    "--ledger",
                    str(self.runtime.ledger.path.resolve()),
                    "--run-id",
                    self.runtime.ledger.run_id,
                    "--task-id",
                    self.runtime.ledger.task_id,
                    "--image",
                    self.executor_image,
                    "--image-id",
                    self.executor_image_id,
                    "--interpreter",
                    self.interpreter,
                    "--test-command",
                    self.test_command,
                ),
                stage_id="implementation",
                actor="executor",
                access="network",
                # The child bridge records model and command work individually.
                # This parent span is harness overhead; counting it as effective
                # work would double-count the complete child runtime.
                time_category="harness_overhead",
                timeout_seconds=3600,
            )
        finally:
            if task_path is not None and task_path.exists():
                task_path.unlink()
        summary = _last_json_object(result.stdout)
        if result.returncode != 0 or summary.get("status") != "passed":
            raise RuntimeError("mini-SWE-agent CLI task execution did not reach a valid terminal submission")
        return summary

    def assert_ready(self) -> None:
        if self.descriptor.implementation_status not in READY_STATUSES:
            raise MiniSweNotReadyError(
                f"mini-SWE-agent is {self.descriptor.implementation_status}; no task session started"
            )

    def _container_command(self, *arguments: str) -> tuple[str, ...]:
        if not arguments or any(not argument for argument in arguments):
            raise ValueError("container command requires non-empty arguments")
        return self._base_container_command() + arguments

    def _workspace_probe_command(self) -> tuple[str, ...]:
        probe = (
            "from pathlib import Path; import os; "
            "assert Path('/workspace').is_dir(); "
            "assert os.environ.get('BENCHMARK_PERMISSION_MODE') == 'approve-reads'; "
            "print('mini-swe workspace boundary ok')"
        )
        return self._base_container_command(mount_workspace=True, entrypoint="python3") + ("-c", probe)

    def _model_probe_command(self) -> tuple[str, ...]:
        return self._container_command(
            "--model",
            "invalid/model",
            "--task",
            "benchmark preflight: do not modify anything",
            "--exit-immediately",
        )

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


def _last_json_object(output: str) -> dict[str, Any]:
    decoder = json.JSONDecoder()
    candidates: list[dict[str, Any]] = []
    for index, character in enumerate(output):
        if character != "{":
            continue
        try:
            value, _ = decoder.raw_decode(output[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            candidates.append(value)
    if not candidates:
        raise ValueError("mini-SWE-agent runner returned no JSON summary")
    return candidates[-1]
