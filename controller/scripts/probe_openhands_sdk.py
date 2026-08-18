#!/usr/bin/env python3
"""Resolve and probe OpenHands SDK in a clean pinned uv/Python container."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from benchmark_controller.ledger import Ledger

IMAGE = "ghcr.io/astral-sh/uv:python3.12-bookworm-slim@sha256:e5b65587bce7de595f299855d7385fe7fca39b8a74baa261ba1b7147afa78e58"
PACKAGES = (
    "openhands-sdk==1.42.1",
    "openhands-tools==1.42.1",
    "openhands-workspace==1.42.1",
)
IGNORED = {".git", ".next", ".DS_Store", "node_modules"}


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


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
    if len(candidates) != 1:
        raise ValueError("expected exactly one structured OpenHands native result")
    return candidates[0]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--confirm", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--ledger", type=Path, required=True)
    args = parser.parse_args()
    if not args.confirm:
        print(json.dumps({"executable": False, "reason": "operator confirmation required"}))
        return 2

    root = Path(__file__).resolve().parents[2]
    fixture = root / "products" / "greenfield"
    native_probe = root / "controller" / "scripts" / "openhands_native_probe.py"
    before = tree_sha256(fixture)
    name = f"benchmark-openhands-{int(time.time())}"
    tag = f"agentic-sdlc-openhands-readiness:{int(time.time())}"
    dockerfile = "\n".join((
        f"FROM {IMAGE}",
        "ENV OPENHANDS_SUPPRESS_BANNER=1",
        "RUN uv pip install --system " + " ".join(PACKAGES),
        "COPY openhands_native_probe.py /probe.py",
        "COPY fixture /workspace",
        "WORKDIR /workspace",
        'CMD ["python", "/probe.py"]',
        "",
    ))
    ledger = Ledger(args.ledger, run_id="run_openhands-sdk-readiness", task_id="pilot_smoke")
    with tempfile.TemporaryDirectory(prefix="agentic-sdlc-openhands-build-") as directory:
        context = Path(directory)
        shutil.copy2(native_probe, context / "openhands_native_probe.py")
        shutil.copytree(fixture, context / "fixture", ignore=shutil.ignore_patterns(*IGNORED))
        (context / "Dockerfile").write_text(dockerfile, encoding="utf-8")
        build_command = (
            "docker", "build", "--no-cache", "--label", "agentic-sdlc-benchmark=openhands-readiness",
            "--tag", tag, str(context),
        )
        started = time.monotonic_ns()
        build = subprocess.run(build_command, capture_output=True, text=True, check=False, timeout=600)
        duration_ms = (time.monotonic_ns() - started) / 1_000_000
    run_command = (
        "docker", "run", "--rm", "--name", name, "--read-only", "--network", "none",
        "--cap-drop=ALL", "--security-opt", "no-new-privileges", "--pids-limit", "256",
        "--memory", "4g", "--tmpfs", "/tmp:rw,noexec,nosuid,size=64m", tag,
    )
    runtime = subprocess.run(run_command, capture_output=True, text=True, check=False, timeout=120) if build.returncode == 0 else None
    combined = build.stdout + build.stderr + (runtime.stdout + runtime.stderr if runtime else "")
    native: dict[str, Any] = {}
    error: str | None = None
    try:
        native = parse_native_result(runtime.stdout + runtime.stderr if runtime else "")
    except ValueError as exc:
        error = str(exc)
    inspect = subprocess.run(
        ("docker", "ps", "-a", "--filter", f"name=^{name}$", "--format", "{{.ID}}"),
        capture_output=True, text=True, check=False,
    )
    container_removed = inspect.returncode == 0 and not inspect.stdout.strip()
    image_inspect = subprocess.run(
        ("docker", "image", "inspect", tag, "--format", "{{.Id}}"),
        capture_output=True, text=True, check=False,
    )
    image_id_sha256 = sha256_bytes(image_inspect.stdout.strip().encode()) if image_inspect.returncode == 0 else None
    image_remove = subprocess.run(("docker", "image", "rm", tag), capture_output=True, text=True, check=False)
    image_removed = image_remove.returncode == 0
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
        ("harness.cleanup", "completed" if container_removed else "failed"),
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
        "resolver_policy": {"no_deps": False, "dependency_overrides": False, "pre_release": False},
        "image": IMAGE,
        "packages": list(PACKAGES),
        "build_command_sha256": sha256_bytes(json.dumps(build_command, separators=(",", ":")).encode()),
        "run_command_sha256": sha256_bytes(json.dumps(run_command, separators=(",", ":")).encode()),
        "probe_source_sha256": sha256_bytes(Path(__file__).read_bytes()),
        "native_probe_source_sha256": sha256_bytes(native_probe.read_bytes()),
        "resolver_returncode": build.returncode,
        "runtime_returncode": runtime.returncode if runtime else None,
        "resolver_output_sha256": sha256_bytes(combined.encode()),
        "native": native,
        "fixture_tree_sha256": before,
        "workspace_unchanged": native.get("workspace_tree_sha256") == before,
        "built_image_id_sha256": image_id_sha256,
        "container_removed": container_removed,
        "image_removed": image_removed,
        "ledger_event_count": 4,
        "ledger_sha256": sha256_bytes(args.ledger.read_bytes()),
        "raw_output_persisted": False,
    }
    if error:
        result["error"] = error
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": result["status"], "output": str(args.output)}))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
