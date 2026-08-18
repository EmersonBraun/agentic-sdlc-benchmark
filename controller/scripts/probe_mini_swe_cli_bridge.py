#!/usr/bin/env python3
"""Run a bounded mini-SWE-agent technical probe through authenticated Grok CLI."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import time
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "controller" / "src"))

from benchmark_controller.ledger import Ledger  # noqa: E402
from benchmark_controller.mini_swe_cli_model import GrokCliModel  # noqa: E402

from minisweagent.agents.default import DefaultAgent  # noqa: E402
from minisweagent.environments.docker import DockerEnvironment  # noqa: E402
from minisweagent.exceptions import Submitted  # noqa: E402


EXECUTOR_IMAGE = "agentic-sdlc-greenfield:preflight-v1.0"
EXECUTOR_IMAGE_ID = "sha256:437f9f730d5aeae089461f4949504277637ca1b72b769449d7ebc62402497a1a"


def _sha256(value: str | bytes) -> str:
    raw = value.encode("utf-8") if isinstance(value, str) else value
    return hashlib.sha256(raw).hexdigest()


def _workspace_hash(workspace: Path, *, exclude: set[str] | None = None) -> str:
    ignored = exclude or set()
    digest = hashlib.sha256()
    for path in sorted(workspace.rglob("*")):
        relative = path.relative_to(workspace).as_posix()
        if relative in ignored or relative == "node_modules" or relative.startswith("node_modules/"):
            continue
        if path.is_symlink():
            digest.update(f"L:{relative}:{path.readlink()}\n".encode("utf-8"))
        elif path.is_file():
            digest.update(f"F:{relative}:".encode("utf-8"))
            digest.update(path.read_bytes())
    return digest.hexdigest()


def _workspace_manifest(workspace: Path, *, exclude: set[str] | None = None) -> dict[str, str]:
    ignored = exclude or set()
    manifest: dict[str, str] = {}
    for path in sorted(workspace.rglob("*")):
        relative = path.relative_to(workspace).as_posix()
        if relative in ignored or relative == "node_modules" or relative.startswith("node_modules/"):
            continue
        if path.is_symlink():
            manifest[relative] = _sha256(f"link:{path.readlink()}")
        elif path.is_file():
            manifest[relative] = _sha256(path.read_bytes())
    return manifest


class LedgeredModel:
    def __init__(self, model: GrokCliModel, ledger: Ledger) -> None:
        self.model = model
        self.ledger = ledger

    def query(self, messages: list[dict[str, Any]], **kwargs: Any) -> dict[str, Any]:
        started = time.monotonic_ns()
        try:
            result = self.model.query(messages, **kwargs)
        except Exception as exc:
            self.ledger.record(
                stage_id="implementation",
                actor="executor",
                event_type="harness.model.query",
                time_category="effective_work",
                duration_ms=(time.monotonic_ns() - started) / 1_000_000,
                status="failed",
                payload={"error_type": type(exc).__name__, "message_count": len(messages)},
                tool="mini-swe-agent:grok-cli",
            )
            raise
        self.ledger.record(
            stage_id="implementation",
            actor="executor",
            event_type="harness.model.query",
            time_category="effective_work",
            duration_ms=(time.monotonic_ns() - started) / 1_000_000,
            status="completed",
            payload={"message_count": len(messages), "action_count": len(result["extra"]["actions"])},
            tool="mini-swe-agent:grok-cli",
            cost_usd=float(result["extra"].get("cost", 0.0)),
        )
        return result

    def __getattr__(self, name: str) -> Any:
        return getattr(self.model, name)


class LedgeredEnvironment:
    def __init__(self, environment: DockerEnvironment, ledger: Ledger, *, test_command: str) -> None:
        self.environment = environment
        self.ledger = ledger
        self.test_command = test_command
        self.test_command_observed = False
        self.returncodes: list[int] = []
        self.test_returncodes: list[int] = []

    def execute(self, action: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        started = time.monotonic_ns()
        command_hash = _sha256(str(action.get("command", "")))
        is_test_command = self.test_command in str(action.get("command", ""))
        self.test_command_observed |= is_test_command
        try:
            result = self.environment.execute(action, **kwargs)
        except Submitted:
            self.returncodes.append(0)
            self.ledger.record(
                stage_id="implementation",
                actor="executor",
                event_type="harness.command.executed",
                time_category="effective_work",
                duration_ms=(time.monotonic_ns() - started) / 1_000_000,
                status="completed",
                payload={"command_sha256": command_hash, "submitted": True},
                tool="mini-swe-agent:docker",
            )
            raise
        self.ledger.record(
            stage_id="implementation",
            actor="executor",
            event_type="harness.command.executed",
            time_category="effective_work",
            duration_ms=(time.monotonic_ns() - started) / 1_000_000,
            status="completed" if result.get("returncode") == 0 else "failed",
            payload={
                "command_sha256": command_hash,
                "returncode": result.get("returncode"),
                "output_length": len(result.get("output", "")),
            },
            tool="mini-swe-agent:docker",
        )
        self.returncodes.append(int(result.get("returncode", -1)))
        if is_test_command:
            self.test_returncodes.append(int(result.get("returncode", -1)))
        return result

    def __getattr__(self, name: str) -> Any:
        return getattr(self.environment, name)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path)
    parser.add_argument("--task-file", type=Path)
    parser.add_argument("--ledger", type=Path)
    parser.add_argument("--run-id")
    parser.add_argument("--task-id")
    parser.add_argument("--technical-source", type=Path, default=ROOT / "products" / "greenfield")
    parser.add_argument("--image", default=EXECUTOR_IMAGE)
    parser.add_argument("--image-id", default=EXECUTOR_IMAGE_ID)
    parser.add_argument("--test-command", default="./node_modules/.bin/vitest run")
    parser.add_argument("--interpreter", choices=("bash", "sh"), default="bash")
    args = parser.parse_args()
    live_values = (args.workspace, args.task_file, args.ledger, args.run_id, args.task_id)
    if any(value is not None for value in live_values) and not all(value is not None for value in live_values):
        parser.error("live execution requires --workspace, --task-file, --ledger, --run-id, and --task-id")
    technical_probe = args.workspace is None

    with tempfile.TemporaryDirectory(prefix="agentic-sdlc-mini-swe-cli-") as directory:
        root = Path(directory)
        workspace = (root / "workspace") if technical_probe else args.workspace.resolve()
        if technical_probe:
            shutil.copytree(
                args.technical_source,
                workspace,
                ignore=shutil.ignore_patterns("node_modules", ".next", ".git", ".DS_Store"),
            )
        if not workspace.is_dir():
            parser.error("workspace must be an existing directory")
        dependency_link = workspace / "node_modules"
        dependency_link_created = not dependency_link.exists()
        if dependency_link_created:
            dependency_link.symlink_to("/app/node_modules", target_is_directory=True)
        baseline_manifest = _workspace_manifest(workspace)
        baseline_hash = _workspace_hash(workspace)
        ledger_path = (root / "ledger.jsonl") if technical_probe else args.ledger.resolve()
        ledger = Ledger(
            ledger_path,
            run_id="run_mini-swe-cli-probe" if technical_probe else args.run_id,
            task_id="pilot_mini-swe-cli" if technical_probe else args.task_id,
        )
        environment: DockerEnvironment | None = None
        container_id: str | None = None
        submitted = False
        cleanup_passed = False
        error_type: str | None = None
        ledgered_environment: LedgeredEnvironment | None = None
        verification_test_returncode: int | None = None
        actual_image_id: str | None = None
        try:
            inspected = subprocess.run(
                ("docker", "image", "inspect", args.image, "--format", "{{.Id}}"),
                capture_output=True,
                text=True,
                check=False,
                timeout=30,
            )
            actual_image_id = inspected.stdout.strip() if inspected.returncode == 0 else None
            if actual_image_id != args.image_id:
                raise RuntimeError("executor image identity does not match the frozen snapshot")
            with ledger.span(
                stage_id="intake",
                actor="infrastructure",
                event_type="harness.container.started",
                time_category="harness_overhead",
                payload={"image": args.image, "network": "none"},
                tool="mini-swe-agent:docker",
            ):
                environment = DockerEnvironment(
                    image=args.image,
                    cwd="/workspace",
                    timeout=600,
                    container_timeout="15m",
                    interpreter=[args.interpreter, "-lc"],
                    run_args=[
                        "--rm",
                        "--network",
                        "none",
                        "--read-only",
                        "--tmpfs",
                        "/tmp:rw,nosuid,nodev,noexec,size=64m",
                        "--tmpfs",
                        "/app/node_modules/.vite-temp:rw,nosuid,nodev,noexec,size=64m",
                        "--cap-drop=ALL",
                        "--security-opt=no-new-privileges",
                        "--mount",
                        f"type=bind,src={workspace},dst=/workspace",
                    ],
                )
                container_id = environment.container_id
            model = LedgeredModel(GrokCliModel(model_name="grok-4.5"), ledger)
            ledgered_environment = LedgeredEnvironment(environment, ledger, test_command=args.test_command)
            task = (
                "Technical bridge probe; do not access the network or other paths."
                if technical_probe
                else args.task_file.read_text(encoding="utf-8")
            )
            instructions = (
                "{{task}} Use shell commands only through the harness. Do not modify existing files. "
                f"Run the existing test suite with {args.test_command}, create result.txt containing exactly "
                "MINI_SWE_CLI_BRIDGE_OK followed by a newline, verify it, then submit with the required "
                "completion command."
                if technical_probe
                else (
                    "{{task}} Use shell commands only through the harness. Work only inside /workspace. "
                    "Inspect before editing, implement the requested change, run the relevant tests, and "
                    "submit only after verification with the required completion command."
                )
            )
            agent = DefaultAgent(
                model,
                ledgered_environment,
                system_template="You are a bounded software executor.",
                instance_template=instructions,
                step_limit=16 if technical_probe else 40,
                cost_limit=0,
                wall_time_limit_seconds=600,
                max_consecutive_format_errors=1,
            )
            result = agent.run(task=task)
            submitted = result.get("exit_status") == "Submitted"
            verification = ledgered_environment.execute({"command": args.test_command})
            verification_test_returncode = int(verification.get("returncode", -1))
        except Exception as exc:
            error_type = type(exc).__name__
        finally:
            if environment is not None and container_id:
                stopped = subprocess.run(
                    ("docker", "stop", "--time", "3", container_id),
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=15,
                )
                cleanup_passed = stopped.returncode == 0
                environment.container_id = None
                ledger.record(
                    stage_id="documentation",
                    actor="infrastructure",
                    event_type="harness.container.cleaned",
                    time_category="harness_overhead",
                    duration_ms=0,
                    status="completed" if cleanup_passed else "failed",
                    payload={"container_id_sha256": _sha256(container_id)},
                    tool="mini-swe-agent:docker",
                )
            if dependency_link_created and dependency_link.is_symlink():
                dependency_link.unlink()

        result_path = workspace / "result.txt"
        artifact_passed = (
            result_path.is_file() and result_path.read_text(encoding="utf-8") == "MINI_SWE_CLI_BRIDGE_OK\n"
            if technical_probe
            else None
        )
        source_unchanged = (
            _workspace_hash(workspace, exclude={"result.txt"}) == baseline_hash if technical_probe else None
        )
        final_manifest = _workspace_manifest(workspace, exclude={"result.txt"}) if technical_probe else {}
        unexpected_paths = sorted(
            path
            for path in set(baseline_manifest) | set(final_manifest)
            if baseline_manifest.get(path) != final_manifest.get(path)
        )
        test_command_observed = bool(ledgered_environment and ledgered_environment.test_command_observed)
        events = [json.loads(line) for line in ledger_path.read_text(encoding="utf-8").splitlines()]
        event_counts = Counter(event["event_type"] for event in events)
        passed = submitted and cleanup_passed and verification_test_returncode == 0 and error_type is None
        if technical_probe:
            passed = passed and bool(artifact_passed and source_unchanged and test_command_observed)
        attestation = {
            "schema_version": "mini-swe-cli-bridge-attestation-v1.1",
            "protocol_version": "v1.1",
            "status": "passed" if passed else "failed",
            "mode": "technical-probe" if technical_probe else "task-execution",
            "harness": {"name": "mini-SWE-agent", "version": "2.4.6"},
            "model_transport": {
                "provider": "grok",
                "model": "grok-4.5",
                "transport": "native-cli-oauth",
                "model_tools_enabled": False,
                "model_web_enabled": False,
                "model_memory_enabled": False,
                "session_cleanup": "passed" if passed else "unverified",
            },
            "environment": {
                "image": args.image,
                "image_id": actual_image_id,
                "image_identity_verified": actual_image_id == args.image_id,
                "network": "none",
                "root_filesystem": "read-only",
                "ephemeral_test_cache": "/app/node_modules/.vite-temp",
                "interpreter": args.interpreter,
                "workspace_mount": "read-write-isolated-fixture" if technical_probe else "read-write-run-workspace",
                "cleanup": "passed" if cleanup_passed else "failed",
            },
            "probe": {
                "submitted": submitted,
                "artifact_passed": artifact_passed,
                "product_tests_executed": test_command_observed,
                "command_count": len(ledgered_environment.returncodes) if ledgered_environment else 0,
                "failed_command_count": (
                    sum(code != 0 for code in ledgered_environment.returncodes) if ledgered_environment else 0
                ),
                "product_test_returncodes": ledgered_environment.test_returncodes if ledgered_environment else [],
                "independent_verification_test_returncode": verification_test_returncode,
                "source_unchanged": source_unchanged,
                "unexpected_paths": unexpected_paths,
                "artifact_sha256": (
                    _sha256(result_path.read_bytes()) if technical_probe and result_path.is_file() else None
                ),
                "error_type": error_type,
            },
            "ledger": {
                "event_count": len(events),
                "event_type_counts": dict(sorted(event_counts.items())),
                "ledger_sha256": _sha256(ledger_path.read_bytes()),
                "raw_prompts_published": False,
                "raw_responses_published": False,
                "raw_commands_published": False,
            },
        }
        print(json.dumps(attestation, indent=2, sort_keys=True))
        return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
