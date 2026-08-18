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

import yaml

from .adapters import HARNESS_DESCRIPTORS, ComponentDescriptor
from .external import AccessType, AdapterCommandResult, ControlledAdapter, PermissionMode, _validate_command
from .ledger import Ledger

IMAGE = "ghcr.io/astral-sh/uv:python3.12-bookworm-slim@sha256:e5b65587bce7de595f299855d7385fe7fca39b8a74baa261ba1b7147afa78e58"
NODE_IMAGE = "node:22.13.0-bookworm-slim@sha256:f5a0871ab03b035c58bdb3007c3d177b001c2145c18e81817b71624dcf7d8bff"
RUNTIME_IMAGE = "agentic-sdlc-openhands-runtime:1.42.1-node22"
CONTEXT_IGNORED = {".next", ".DS_Store", "node_modules"}
EXPORT_IGNORED = {".next", ".DS_Store", "node_modules"}


class OpenHandsSDKAdapter:
    """Execute commands through LocalWorkspace and return scoped writes to the workspace."""

    def __init__(self, workspace: Path, ledger: Ledger, *, permission_mode: PermissionMode) -> None:
        self.descriptor: ComponentDescriptor = HARNESS_DESCRIPTORS["openhands-sdk"]
        self.runtime = ControlledAdapter(workspace, ledger, permission_mode=permission_mode)
        self._root = Path(__file__).resolve().parents[3]
        self.runtime_image_id: str | None = None

    def assert_ready(self) -> None:
        if self.descriptor.implementation_status not in {"contract-ready", "installed-ready"}:
            raise RuntimeError(f"OpenHands SDK is {self.descriptor.implementation_status}")

    def prepare_runtime(self) -> str:
        """Materialize the network-dependent image as an explicit audited operation."""
        try:
            self.runtime.permissions.authorize("network")
        except PermissionError:
            self.runtime.ledger.record(
                stage_id="intake", actor="infrastructure", event_type="harness.runtime.materialization.blocked",
                time_category="orchestration_overhead", duration_ms=0, status="blocked",
                payload={"access": "network"}, tool="openhands-sdk-container-adapter-v1.1",
            )
            raise
        self.runtime.prepare()
        try:
            _assert_supported_dependency_layout(self.runtime.workspace)
        except ValueError:
            self.runtime.ledger.record(
                stage_id="intake", actor="infrastructure", event_type="harness.runtime.materialized",
                time_category="harness_overhead", duration_ms=0, status="failed",
                payload={"unsupported_dependency_layout": True}, tool="openhands-sdk-container-adapter-v1.1",
            )
            raise
        with tempfile.TemporaryDirectory(prefix="agentic-sdlc-openhands-runtime-") as directory:
            context = Path(directory)
            dependency_manifest = context / "dependency-manifest"
            dependency_manifest.mkdir()
            for filename in ("package.json", "pnpm-lock.yaml", "pnpm-workspace.yaml"):
                source = self.runtime.workspace / filename
                if source.is_file():
                    shutil.copy2(source, dependency_manifest / filename)
            shutil.copy2(self._root / "controller/scripts/openhands_command_bridge.py", context / "bridge.py")
            shutil.copy2(self._root / "adapters/openhands-sdk-v1.1.requirements.lock", context / "requirements.lock")
            (context / "Dockerfile").write_text(_runtime_dockerfile(), encoding="utf-8")
            started = time.monotonic_ns()
            built = _safe_run(
                ("docker", "build", "--no-cache", "--tag", RUNTIME_IMAGE, str(context)),
                capture_output=True, text=True, timeout=600, check=False,
            )
        inspected = _safe_run(
            ("docker", "image", "inspect", RUNTIME_IMAGE, "--format", "{{.Id}}"),
            capture_output=True, text=True, check=False,
        )
        image_id = inspected.stdout.strip() if inspected.returncode == 0 else ""
        self.runtime.ledger.record(
            stage_id="intake", actor="infrastructure", event_type="harness.runtime.materialized",
            time_category="harness_overhead", duration_ms=(time.monotonic_ns() - started) / 1_000_000,
            status="completed" if built.returncode == 0 and image_id.startswith("sha256:") else "failed",
            payload={"image_id_sha256": hashlib.sha256(image_id.encode()).hexdigest()},
            tool="openhands-sdk-container-adapter-v1.1",
        )
        if built.returncode != 0 or not image_id.startswith("sha256:"):
            raise RuntimeError("OpenHands runtime materialization failed")
        self.runtime_image_id = image_id
        return image_id

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
        try:
            self.runtime.permissions.authorize(access)
        except PermissionError:
            self.runtime.ledger.record(
                stage_id=stage_id, actor=actor, event_type="adapter.command.blocked",
                time_category="orchestration_overhead", duration_ms=0, status="blocked",
                payload={"access": access}, tool="openhands-sdk-container-adapter-v1.1",
            )
            raise
        self.runtime.prepare()
        container = f"benchmark-openhands-command-{time.time_ns()}"
        readonly_image = f"agentic-sdlc-openhands-readonly:{time.time_ns()}"
        container_removed = False
        runtime_available = False
        readonly_image_removed = access != "read"
        pending_error: Exception | None = None
        started = time.monotonic_ns()
        result = AdapterCommandResult(normalized, 125, "", "OpenHands command did not start")
        with tempfile.TemporaryDirectory(prefix="agentic-sdlc-openhands-command-") as directory:
            context = Path(directory)
            shutil.copytree(self.runtime.workspace, context / "workspace", ignore=shutil.ignore_patterns(*CONTEXT_IGNORED))
            (context / "workspace" / "node_modules").symlink_to("/opt/product-node_modules", target_is_directory=True)
            image_probe = _safe_run(("docker", "image", "inspect", RUNTIME_IMAGE, "--format", "{{.Id}}"))
            if self.runtime_image_id is None or image_probe.returncode != 0 or image_probe.stdout.strip() != self.runtime_image_id:
                self.runtime.ledger.record(
                    stage_id=stage_id, actor=actor, event_type="adapter.command.executed",
                    time_category=time_category, duration_ms=(time.monotonic_ns() - started) / 1_000_000,
                    status="failed", payload={"access": access, "runtime_identity_verified": False},
                    tool="openhands-sdk-container-adapter-v1.1",
                )
                raise RuntimeError("OpenHands runtime is not materialized; call prepare_runtime() with network permission")
            run = ["docker", "create", "--name", container]
            if access != "network":
                run += ["--network", "none"]
            run += ["--cap-drop=ALL", "--cap-add=DAC_OVERRIDE", "--security-opt=no-new-privileges", "--pids-limit", "256"]
            run += ["--tmpfs", "/tmp:rw,noexec,nosuid,size=64m", self.runtime_image_id, "python", "/bridge.py", json.dumps(normalized)]
            try:
                created = subprocess.run(run, capture_output=True, text=True, check=False)
                if created.returncode != 0:
                    raise RuntimeError("failed to create OpenHands runtime container")
                imported = subprocess.run(("docker", "cp", f"{context / 'workspace'}/.", f"{container}:/workspace/"), capture_output=True, text=True, check=False)
                if imported.returncode != 0:
                    raise RuntimeError("failed to import OpenHands workspace")
                if access == "read":
                    committed = subprocess.run(("docker", "commit", container, readonly_image), capture_output=True, text=True, check=False)
                    _safe_run(("docker", "rm", "--force", container))
                    if committed.returncode != 0:
                        raise RuntimeError("failed to freeze read-only OpenHands workspace")
                    readonly_run = list(run)
                    readonly_run.insert(readonly_run.index(self.runtime_image_id), "--read-only")
                    readonly_run[readonly_run.index(self.runtime_image_id)] = readonly_image
                    recreated = subprocess.run(readonly_run, capture_output=True, text=True, check=False)
                    if recreated.returncode != 0:
                        raise RuntimeError("failed to create read-only OpenHands runtime container")
                completed = subprocess.run(("docker", "start", "--attach", container), capture_output=True, text=True, timeout=timeout_seconds, check=False)
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
            except Exception as exc:
                pending_error = exc
                result = AdapterCommandResult(normalized, 125, "", type(exc).__name__)
            finally:
                _safe_run(("docker", "rm", "--force", container))
                _safe_run(("docker", "image", "rm", "--force", readonly_image))
                container_removed = _confirmed_absent(("docker", "container", "inspect", container))
                if access == "read":
                    readonly_image_removed = _confirmed_absent(("docker", "image", "inspect", readonly_image))
                runtime_check = _safe_run(("docker", "image", "inspect", self.runtime_image_id, "--format", "{{.Id}}"))
                runtime_available = runtime_check.returncode == 0 and runtime_check.stdout.strip() == self.runtime_image_id
        duration_ms = (time.monotonic_ns() - started) / 1_000_000
        self.runtime.ledger.record(
            stage_id=stage_id, actor=actor, event_type="adapter.command.executed",
            time_category=time_category, duration_ms=duration_ms,
            status="completed" if result.returncode == 0 and container_removed and readonly_image_removed and runtime_available else "failed",
            payload={
                "argv_sha256": hashlib.sha256(json.dumps(normalized, separators=(",", ":")).encode()).hexdigest(),
                "access": access, "returncode": result.returncode, "timed_out": result.timed_out,
                "container_removed": container_removed, "readonly_image_removed": readonly_image_removed,
                "runtime_available": runtime_available,
            }, tool="openhands-sdk-container-adapter-v1.1",
        )
        if not container_removed or not readonly_image_removed or not runtime_available:
            raise RuntimeError("OpenHands container cleanup could not be verified")
        if pending_error is not None:
            raise pending_error
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


def _runtime_dockerfile() -> str:
    return "\n".join((
        f"FROM {NODE_IMAGE} AS node_runtime", f"FROM {IMAGE}",
        "COPY --from=node_runtime /usr/local /usr/local",
        "RUN apt-get update && apt-get install --yes --no-install-recommends git=1:2.39.5-0+deb12u3 && rm -rf /var/lib/apt/lists/*",
        "RUN git config --system --add safe.directory /workspace",
        "COPY requirements.lock /requirements.lock",
        "RUN uv pip install --system --require-hashes -r /requirements.lock",
        "RUN npm install --global pnpm@11.21.0", "COPY bridge.py /bridge.py",
        "COPY dependency-manifest /build-workspace",
        "RUN if [ -f /build-workspace/pnpm-lock.yaml ]; then cd /build-workspace && pnpm install --frozen-lockfile && mv node_modules /opt/product-node_modules; fi && rm -rf /build-workspace && mkdir /workspace",
        "WORKDIR /workspace", "",
    ))


def _assert_supported_dependency_layout(workspace: Path) -> None:
    package_file = workspace / "package.json"
    if package_file.is_file():
        package = json.loads(package_file.read_text(encoding="utf-8"))
        dependency_groups = ("dependencies", "devDependencies", "optionalDependencies", "peerDependencies")
        values = [value for group in dependency_groups for value in package.get(group, {}).values()]
        if any(isinstance(value, str) and value.startswith(("workspace:", "file:", "link:")) for value in values):
            raise ValueError("local package dependencies are not supported by the isolated runtime materializer")
    workspace_file = workspace / "pnpm-workspace.yaml"
    if workspace_file.is_file():
        workspace_config = yaml.safe_load(workspace_file.read_text(encoding="utf-8")) or {}
        if not isinstance(workspace_config, dict):
            raise ValueError("pnpm workspace configuration must be a mapping")
        if workspace_config.get("packages"):
            raise ValueError("multi-package pnpm workspaces are not supported by the isolated runtime materializer")


def _confirmed_absent(command: tuple[str, ...]) -> bool:
    result = _safe_run(command)
    return result.returncode != 0 and "No such" in result.stderr


def _safe_run(command: tuple[str, ...], **kwargs: object) -> subprocess.CompletedProcess[str]:
    try:
        options = {"capture_output": True, "text": True, "check": False, **kwargs}
        return subprocess.run(command, **options)  # type: ignore[arg-type]
    except subprocess.TimeoutExpired as exc:
        return subprocess.CompletedProcess(command, 124, exc.stdout or "", exc.stderr or "")
    except OSError as exc:
        return subprocess.CompletedProcess(command, 125, "", f"{type(exc).__name__}: {exc}")


def _replace_workspace(target: Path, source: Path) -> None:
    for child in target.iterdir():
        if child.name not in EXPORT_IGNORED:
            if child.is_dir() and not child.is_symlink():
                shutil.rmtree(child)
            else:
                child.unlink()
    for child in source.iterdir():
        if child.name in EXPORT_IGNORED:
            continue
        destination = target / child.name
        if child.is_dir() and not child.is_symlink():
            shutil.copytree(child, destination)
        else:
            shutil.copy2(child, destination, follow_symlinks=False)
