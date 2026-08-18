#!/usr/bin/env python3
"""Resolve and probe OpenHands SDK in a clean pinned uv/Python container."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from benchmark_controller.ledger import Ledger

IMAGE = "ghcr.io/astral-sh/uv:python3.12-bookworm-slim@sha256:e5b65587bce7de595f299855d7385fe7fca39b8a74baa261ba1b7147afa78e58"
IGNORED = {".git", ".next", ".DS_Store", "node_modules"}
NATIVE_FIELDS = {
    "schema_version", "versions", "versions_exact", "workspace_type", "read_exit_code",
    "read_marker_observed", "read_stdout_sha256", "write_exit_code", "write_denied",
    "write_stderr_sha256", "workspace_tree_sha256", "raw_content_in_result",
}
EXPECTED_VERSIONS = {
    "openhands-sdk": "1.42.1", "openhands-tools": "1.42.1",
    "openhands-workspace": "1.42.1", "openhands-agent-server": "1.42.1",
}
SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def safe_run(command: tuple[str, ...]) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(command, capture_output=True, text=True, check=False)
    except OSError as exc:
        return subprocess.CompletedProcess(command, 125, "", f"{type(exc).__name__}: {exc}")


def tree_sha256(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        if any(part in IGNORED for part in relative.parts):
            continue
        digest.update(str(relative).encode())
        if path.is_symlink():
            digest.update(b"symlink\0" + str(path.readlink()).encode())
        elif path.is_file():
            digest.update(b"file\0" + path.read_bytes())
        else:
            digest.update(b"dir\0")
    return digest.hexdigest()


def parse_native_result(output: str) -> dict[str, Any]:
    candidates = []
    for line in output.splitlines():
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict) and value.get("schema_version") == "openhands-native-probe-v1.1":
            candidates.append(value)
    if len(candidates) != 1 or set(candidates[0]) != NATIVE_FIELDS:
        raise ValueError("expected exactly one exact-schema OpenHands native result")
    result = candidates[0]
    bool_fields = ("versions_exact", "read_marker_observed", "write_denied", "raw_content_in_result")
    if any(not isinstance(result[field], bool) for field in bool_fields):
        raise ValueError("native boolean field has invalid type")
    if result["raw_content_in_result"] is not False:
        raise ValueError("native result reports raw content")
    if result["versions"] != EXPECTED_VERSIONS or result["workspace_type"] != "LocalWorkspace":
        raise ValueError("native identity does not match the frozen contract")
    if not isinstance(result["read_exit_code"], int) or isinstance(result["read_exit_code"], bool) or result["read_exit_code"] != 0 or not isinstance(result["write_exit_code"], int) or isinstance(result["write_exit_code"], bool) or result["write_exit_code"] == 0:
        raise ValueError("native exit codes do not prove read/write behavior")
    for field in ("read_stdout_sha256", "write_stderr_sha256", "workspace_tree_sha256"):
        if not isinstance(result[field], str) or SHA256_PATTERN.fullmatch(result[field]) is None:
            raise ValueError(f"{field} is not a SHA-256 digest")
    return result


def execute_probe(
    *, context: Path, dockerfile: str, fixture: Path, native_probe: Path,
    lockfile: Path, name: str, tag: str,
) -> tuple[subprocess.CompletedProcess[str], subprocess.CompletedProcess[str] | None, tuple[str, ...], tuple[str, ...], float, str | None, bool, bool, str | None]:
    """Build/run the probe and always remove its uniquely named Docker artifacts."""
    build_command = (
        "docker", "build", "--no-cache", "--label", "agentic-sdlc-benchmark=openhands-readiness",
        "--tag", tag, str(context),
    )
    run_command = (
        "docker", "run", "--name", name, "--read-only", "--network", "none",
        "--cap-drop=ALL", "--security-opt", "no-new-privileges", "--pids-limit", "256",
        "--memory", "4g", "--tmpfs", "/tmp:rw,noexec,nosuid,size=64m", tag,
    )
    shutil.copy2(native_probe, context / "openhands_native_probe.py")
    shutil.copy2(lockfile, context / "requirements.lock")
    shutil.copytree(fixture, context / "fixture", ignore=shutil.ignore_patterns(*IGNORED))
    (context / "Dockerfile").write_text(dockerfile, encoding="utf-8")
    started = time.monotonic_ns()
    runtime: subprocess.CompletedProcess[str] | None = None
    build = subprocess.CompletedProcess(build_command, 125, "", "build did not start")
    image_id_sha256: str | None = None
    operational_error: str | None = None
    try:
        build = subprocess.run(build_command, capture_output=True, text=True, check=False, timeout=600)
        if build.returncode == 0:
            inspected = subprocess.run(
                ("docker", "image", "inspect", tag, "--format", "{{.Id}}"),
                capture_output=True, text=True, check=False,
            )
            if inspected.returncode == 0:
                image_id_sha256 = sha256_bytes(inspected.stdout.strip().encode())
            runtime = subprocess.run(run_command, capture_output=True, text=True, check=False, timeout=120)
    except subprocess.TimeoutExpired as exc:
        operational_error = f"TimeoutExpired: {exc.timeout} seconds"
        if tuple(exc.cmd) == build_command:
            build = subprocess.CompletedProcess(build_command, 124, exc.stdout or "", exc.stderr or "")
        else:
            runtime = subprocess.CompletedProcess(run_command, 124, exc.stdout or "", exc.stderr or "")
    except OSError as exc:
        operational_error = f"{type(exc).__name__}: {exc}"
    finally:
        safe_run(("docker", "rm", "--force", name))
        safe_run(("docker", "image", "rm", "--force", tag))
    duration_ms = (time.monotonic_ns() - started) / 1_000_000
    container_inspect = safe_run(("docker", "container", "inspect", name))
    image_inspect = safe_run(("docker", "image", "inspect", tag))
    container_removed = container_inspect.returncode != 0 and "No such" in container_inspect.stderr
    image_removed = image_inspect.returncode != 0 and "No such" in image_inspect.stderr
    return build, runtime, build_command, run_command, duration_ms, image_id_sha256, container_removed, image_removed, operational_error


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--confirm", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--ledger", type=Path, required=True)
    args = parser.parse_args()
    if not args.confirm:
        print(json.dumps({"executable": False, "reason": "operator confirmation required"}))
        return 2
    if args.output.exists() or args.ledger.exists():
        raise FileExistsError("output and ledger paths must not exist")

    root = Path(__file__).resolve().parents[2]
    fixture = root / "products" / "greenfield"
    native_probe = root / "controller" / "scripts" / "openhands_native_probe.py"
    command_bridge = root / "controller" / "scripts" / "openhands_command_bridge.py"
    adapter_source = root / "controller" / "src" / "benchmark_controller" / "openhands_sdk.py"
    controller_manifest = root / "controller" / "pyproject.toml"
    validation_workflow = root / ".github" / "workflows" / "validate.yml"
    lockfile = root / "adapters" / "openhands-sdk-v1.1.requirements.lock"
    before = tree_sha256(fixture)
    name = f"benchmark-openhands-{int(time.time())}"
    tag = f"agentic-sdlc-openhands-readiness:{int(time.time())}"
    dockerfile = "\n".join((
        f"FROM {IMAGE}",
        "ENV OPENHANDS_SUPPRESS_BANNER=1",
        "COPY requirements.lock /requirements.lock",
        "RUN uv pip install --system --require-hashes -r /requirements.lock",
        "COPY openhands_native_probe.py /probe.py",
        "COPY fixture /workspace",
        "WORKDIR /workspace",
        'CMD ["python", "/probe.py"]',
        "",
    ))
    ledger = Ledger(args.ledger, run_id="run_openhands-sdk-readiness", task_id="pilot_smoke")
    with tempfile.TemporaryDirectory(prefix="agentic-sdlc-openhands-build-") as directory:
        build, runtime, build_command, run_command, duration_ms, image_id_sha256, container_removed, image_removed, operational_error = execute_probe(
            context=Path(directory), dockerfile=dockerfile, fixture=fixture, native_probe=native_probe,
            lockfile=lockfile, name=name, tag=tag,
        )
    combined = build.stdout + build.stderr + (runtime.stdout + runtime.stderr if runtime else "")
    native: dict[str, Any] = {}
    error: str | None = operational_error
    if error is None:
        try:
            native = parse_native_result(runtime.stdout + runtime.stderr if runtime else "")
        except ValueError as exc:
            error = str(exc)
    passed = all((
        build.returncode == 0,
        runtime is not None and runtime.returncode == 0,
        error is None,
        native.get("versions_exact") is True,
        native.get("read_marker_observed") is True,
        native.get("write_denied") is True,
        native.get("workspace_tree_sha256") == before,
        container_removed,
        image_removed,
    ))
    for event_type, status in (
        ("harness.dependency.resolve", "completed" if build.returncode == 0 else "failed"),
        ("harness.workspace.read", "completed" if native.get("read_marker_observed") else "failed"),
        ("harness.workspace.write", "blocked" if native.get("write_denied") else "failed"),
        ("harness.cleanup", "completed" if container_removed and image_removed else "failed"),
    ):
        ledger.record(
            stage_id="local-testing", actor="infrastructure", event_type=event_type,
            time_category="harness_overhead", duration_ms=duration_ms if "resolve" in event_type else 0,
            status=status, payload={"probe": "openhands-sdk-1.42.1"}, tool="openhands-sdk",
        )
    result = {
        "schema_version": "openhands-sdk-readiness-attestation-v1.1",
        "protocol_version": "v1.1",
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "operator": "local-primary-operator",
        "status": "passed" if passed else "failed",
        "analysis_eligible": False,
        "resolver": "uv",
        "resolver_policy": {"no_deps": False, "dependency_overrides": False, "pre_release": False, "require_hashes": True},
        "image": IMAGE,
        "lock_sha256": sha256_bytes(lockfile.read_bytes()),
        "operator_probe_command": [sys.executable, "controller/scripts/probe_openhands_sdk.py", "--confirm", "--output", str(args.output), "--ledger", str(args.ledger)],
        "container_name_sha256": sha256_bytes(name.encode()),
        "image_tag_sha256": sha256_bytes(tag.encode()),
        "build_command_sha256": sha256_bytes(json.dumps(build_command, separators=(",", ":")).encode()),
        "run_command_sha256": sha256_bytes(json.dumps(run_command, separators=(",", ":")).encode()),
        "probe_source_sha256": sha256_bytes(Path(__file__).read_bytes()),
        "native_probe_source_sha256": sha256_bytes(native_probe.read_bytes()),
        "command_bridge_source_sha256": sha256_bytes(command_bridge.read_bytes()),
        "adapter_source_sha256": sha256_bytes(adapter_source.read_bytes()),
        "controller_manifest_sha256": sha256_bytes(controller_manifest.read_bytes()),
        "validation_workflow_sha256": sha256_bytes(validation_workflow.read_bytes()),
        "resolver_returncode": build.returncode,
        "runtime_returncode": runtime.returncode if runtime else None,
        "resolver_output_sha256": sha256_bytes(combined.encode()),
        "native": native,
        "fixture_tree_sha256": before,
        "workspace_unchanged": native.get("workspace_tree_sha256") == before,
        "built_image_id_sha256": image_id_sha256,
        "container_removed": container_removed,
        "image_removed": image_removed,
        "ledger_event_count": len(args.ledger.read_text().splitlines()),
        "ledger_sha256": sha256_bytes(args.ledger.read_bytes()),
        "raw_output_persisted": False,
    }
    serialized = json.dumps(result, sort_keys=True)
    result["redaction_scan_passed"] = not any(secret in serialized for secret in ("OPENHANDS_WORKSPACE_READY", ".forbidden-write"))
    if not result["redaction_scan_passed"] or result["ledger_event_count"] != 4:
        result["status"] = "failed"
    if error:
        result["error"] = error
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": result["status"], "output": str(args.output)}))
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
