"""OpenHands SDK adapter using a pinned, ephemeral container boundary."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Mapping, Sequence

from .adapters import HARNESS_DESCRIPTORS, ComponentDescriptor
from .external import AccessType, AdapterCommandResult, ControlledAdapter, PermissionMode, _validate_command
from .ledger import Ledger

IMAGE = "ghcr.io/astral-sh/uv:python3.12-bookworm-slim@sha256:e5b65587bce7de595f299855d7385fe7fca39b8a74baa261ba1b7147afa78e58"
IGNORED = {".git", ".next", ".DS_Store", "node_modules"}


class OpenHandsSDKAdapter:
    """Execute commands through LocalWorkspace and return scoped writes to the workspace."""

    def __init__(self, workspace: Path, ledger: Ledger, *, permission_mode: PermissionMode) -> None:
        self.descriptor: ComponentDescriptor = HARNESS_DESCRIPTORS["openhands-sdk"]
        self.runtime = ControlledAdapter(workspace, ledger, permission_mode=permission_mode)
        self._root = Path(__file__).resolve().parents[3]

    def assert_ready(self) -> None:
        if self.descriptor.implementation_status not in {"contract-ready", "installed-ready"}:
            raise RuntimeError(f"OpenHands SDK is {self.descriptor.implementation_status}")

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
        normalized = _validate_command(command)
        if env:
            raise ValueError("OpenHands container adapter does not accept host environment injection")
        if access == "network":
            raise PermissionError("OpenHands collection boundary is network-isolated")
        self.runtime.permissions.authorize(access)
        self.runtime.prepare()
        container = f"benchmark-openhands-command-{time.time_ns()}"
        tag = f"agentic-sdlc-openhands-command:{time.time_ns()}"
        container_removed = False
        image_removed = False
        started = time.monotonic_ns()
        result = AdapterCommandResult(normalized, 125, "", "OpenHands command did not start")
        with tempfile.TemporaryDirectory(prefix="agentic-sdlc-openhands-command-") as directory:
            context = Path(directory)
            shutil.copytree(self.runtime.workspace, context / "workspace", ignore=shutil.ignore_patterns(*IGNORED))
            shutil.copy2(self._root / "controller/scripts/openhands_command_bridge.py", context / "bridge.py")
            shutil.copy2(self._root / "adapters/openhands-sdk-v1.1.requirements.lock", context / "requirements.lock")
            dockerfile = "\n".join((
                f"FROM {IMAGE}",
                "COPY requirements.lock /requirements.lock",
                "RUN uv pip install --system --require-hashes -r /requirements.lock",
                "COPY bridge.py /bridge.py",
                "COPY workspace /workspace",
                "WORKDIR /workspace",
                "",
            ))
            (context / "Dockerfile").write_text(dockerfile, encoding="utf-8")
            build = ("docker", "build", "--quiet", "--tag", tag, str(context))
            run = ["docker", "run", "--name", container, "--network", "none", "--cap-drop=ALL", "--security-opt=no-new-privileges", "--pids-limit", "256"]
            if access == "read":
                run.append("--read-only")
            run += ["--tmpfs", "/tmp:rw,noexec,nosuid,size=64m", tag, "python", "/bridge.py", json.dumps(normalized)]
            try:
                built = subprocess.run(build, capture_output=True, text=True, timeout=600, check=False)
                if built.returncode != 0:
                    result = AdapterCommandResult(normalized, built.returncode, built.stdout, built.stderr)
                else:
                    completed = subprocess.run(run, capture_output=True, text=True, timeout=timeout_seconds, check=False)
                    payload = _parse_result(completed.stdout)
                    result = AdapterCommandResult(normalized, payload["returncode"], payload["stdout"], payload["stderr"])
                    if access == "write":
                        exported = context / "exported"
                        exported.mkdir()
                        copied = subprocess.run(("docker", "cp", f"{container}:/workspace/.", str(exported)), capture_output=True, text=True, check=False)
                        if copied.returncode != 0:
                            raise RuntimeError("failed to export OpenHands workspace")
                        _replace_workspace(self.runtime.workspace, exported)
            except subprocess.TimeoutExpired as exc:
                result = AdapterCommandResult(normalized, 124, exc.stdout or "", exc.stderr or "", timed_out=True)
            finally:
                subprocess.run(("docker", "rm", "--force", container), capture_output=True, text=True, check=False)
                subprocess.run(("docker", "image", "rm", "--force", tag), capture_output=True, text=True, check=False)
                container_removed = not _docker_exists(("docker", "container", "inspect", container))
                image_removed = not _docker_exists(("docker", "image", "inspect", tag))
        duration_ms = (time.monotonic_ns() - started) / 1_000_000
        self.runtime.ledger.record(
            stage_id=stage_id, actor=actor, event_type="adapter.command.executed",
            time_category=time_category, duration_ms=duration_ms,
            status="completed" if result.returncode == 0 and container_removed and image_removed else "failed",
            payload={
                "argv_sha256": hashlib.sha256(json.dumps(normalized, separators=(",", ":")).encode()).hexdigest(),
                "access": access, "returncode": result.returncode, "timed_out": result.timed_out,
                "container_removed": container_removed, "image_removed": image_removed,
            }, tool="openhands-sdk-container-adapter-v1.1",
        )
        if not container_removed or not image_removed:
            raise RuntimeError("OpenHands container cleanup could not be verified")
        return result


def _parse_result(output: str) -> dict[str, object]:
    matches = []
    for line in output.splitlines():
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict) and value.get("schema_version") == "openhands-command-result-v1.1":
            matches.append(value)
    if len(matches) != 1 or set(matches[0]) != {"schema_version", "returncode", "stdout", "stderr"}:
        raise ValueError("invalid OpenHands command result")
    value = matches[0]
    if not isinstance(value["returncode"], int) or not all(isinstance(value[key], str) for key in ("stdout", "stderr")):
        raise ValueError("invalid OpenHands command result types")
    return value


def _docker_exists(command: tuple[str, ...]) -> bool:
    return subprocess.run(command, capture_output=True, text=True, check=False).returncode == 0


def _replace_workspace(target: Path, source: Path) -> None:
    for child in target.iterdir():
        if child.name not in IGNORED:
            if child.is_dir() and not child.is_symlink():
                shutil.rmtree(child)
            else:
                child.unlink()
    for child in source.iterdir():
        destination = target / child.name
        if child.is_dir() and not child.is_symlink():
            shutil.copytree(child, destination)
        else:
            shutil.copy2(child, destination, follow_symlinks=False)
