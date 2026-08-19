"""Execute private quality gates and emit a bounded v1.2 attestation."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import tempfile
import time
from typing import Any, Callable, Mapping

from .v12_evaluation_evidence import COMMAND_KINDS

SHA1 = re.compile(r"^[a-f0-9]{40}$")
SHA256 = re.compile(r"^[a-f0-9]{64}$")
HIDDEN_KEYS = {
    "total", "passed", "failed", "critical_mutants_killed",
    "noncritical_mutant_kill_rate",
}


def _sha(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


class ControllerEvidenceCollector:
    """Deep boundary: private commands in, redacted commit-bound evidence out."""

    def __init__(
        self, private_source_repository: Path | None = None,
        private_source_commit: str | None = None,
        registered_private_source_commit: str | None = None,
    ) -> None:
        self.private_source_repository = (
            private_source_repository.resolve() if private_source_repository else None
        )
        self.private_source_commit = private_source_commit
        self.registered_private_source_commit = registered_private_source_commit

    def collect_for(self, context: Any) -> Path:
        """Refresh evidence immediately before one independent evaluation."""
        head = subprocess.run(
            ("git", "-C", str(context.worktree), "rev-parse", "HEAD"),
            capture_output=True, text=True, check=False,
        )
        if head.returncode:
            raise RuntimeError("collector cannot resolve product commit")
        private = context.bundle.directory / "private-evaluation"
        plan_path = self._configured_plan(context.assignment.task_id)
        started = time.monotonic_ns()

        def record_collection() -> None:
            context.bundle.ledger.record(
                stage_id=context.step.stage_id,
                actor="controller",
                event_type="controller.evidence.collection-boundary",
                time_category="instrumentation_overhead",
                duration_ms=(time.monotonic_ns() - started) / 1_000_000,
                status="started",
                payload={
                    "raw_output_persisted": False,
                    "private_plan_disclosed": False,
                },
                tool="controller-evidence-collector-v1.2",
            )

        return self.collect(
            plan_path=plan_path,
            output_path=private / "controller-attestation.json",
            worktree=context.worktree,
            ledger_path=context.bundle.ledger.path,
            task_id=context.assignment.task_id,
            task_manifest_sha256=context.bundle.manifest["task_manifest_sha256"],
            product_commit=head.stdout.strip(),
            ledger_recorder=record_collection,
            deadline_epoch_ms=context.deadline_epoch_ms,
            expected_private_source_commit=self.private_source_commit,
        )

    def _configured_plan(self, task_id: str) -> Path:
        if self.private_source_repository is None or self.private_source_commit is None:
            raise RuntimeError("private evidence source repository is not configured")
        if not SHA1.fullmatch(self.private_source_commit):
            raise RuntimeError("configured private evidence commit is invalid")
        registered = self.registered_private_source_commit or self._registered_commit(task_id)
        if self.private_source_commit != registered:
            raise RuntimeError("configured private evidence commit is not the public frozen commit")
        if self.private_source_repository.is_symlink():
            raise RuntimeError("private evidence source cannot be a symlink")
        plan = self.private_source_repository / "evidence-plan.json"
        observed = self._verify_private_source(plan)
        if observed != self.private_source_commit:
            raise RuntimeError("private evidence source does not match the frozen commit")
        return plan

    @staticmethod
    def _registered_commit(task_id: str) -> str:
        path = Path(__file__).resolve().parents[3] / "adapters/private-evaluator-v1.2-readiness.json"
        value = json.loads(path.read_text(encoding="utf-8"))
        commit = value.get("private_source_commit") if isinstance(value, Mapping) else None
        if not all((
            value.get("schema_version") == "private-evaluator-readiness-v1.2",
            value.get("status") == "passed",
            value.get("task_id") == task_id,
            isinstance(commit, str),
            bool(SHA1.fullmatch(commit or "")),
        )):
            raise RuntimeError("public frozen private-evaluator registration is invalid")
        return commit

    def collect(
        self, *, plan_path: Path, output_path: Path, worktree: Path,
        ledger_path: Path, task_id: str, task_manifest_sha256: str,
        product_commit: str,
        ledger_recorder: Callable[[], None] | None = None,
        deadline_epoch_ms: float | None = None,
        expected_private_source_commit: str | None = None,
    ) -> Path:
        worktree = worktree.resolve()
        plan_path = plan_path.resolve()
        output_path = output_path.resolve()
        ledger_path = ledger_path.resolve()
        if worktree == plan_path or worktree in plan_path.parents:
            raise ValueError("private evidence plan must be outside the ADE worktree")
        if not SHA1.fullmatch(product_commit) or not SHA256.fullmatch(task_manifest_sha256):
            raise ValueError("collector source identity is invalid")
        self._verify_product(worktree, product_commit)
        private_source_commit = self._verify_private_source(plan_path)
        if (
            expected_private_source_commit is not None
            and private_source_commit != expected_private_source_commit
        ):
            raise RuntimeError("private evidence source commit mismatch")
        plan = self._load_plan(plan_path, task_id)
        output_path.unlink(missing_ok=True)
        if ledger_recorder is not None:
            ledger_recorder()
        ledger_before = ledger_path.read_bytes()
        command_evidence: list[dict[str, Any]] = []
        hidden_summary: Mapping[str, Any] | None = None
        gates: dict[str, bool] = {}
        for kind in sorted(COMMAND_KINDS):
            command = plan["commands"][kind]
            argv = self._argv(
                command["argv"], worktree, ledger_path, output_path.parent.parent,
                plan_path.parent,
            )
            timeout = float(command["timeout_seconds"])
            if deadline_epoch_ms is not None:
                timeout = min(timeout, (deadline_epoch_ms - time.time() * 1000) / 1000)
            if timeout <= 0:
                raise subprocess.TimeoutExpired(argv, 0)
            if kind in {"build", "typecheck"}:
                argv = self._sandboxed(argv, plan_path.parent)
            completed = self._run_command(argv, worktree, timeout)
            output = completed.stdout + completed.stderr
            command_evidence.append({
                "kind": kind,
                "command_sha256": _sha(json.dumps(argv, separators=(",", ":")).encode()),
                "output_sha256": _sha(output),
                "exit_code": completed.returncode,
            })
            gates[self._gate(kind)] = completed.returncode == 0
            if kind == "hidden-tests":
                hidden_summary = self._hidden_summary(completed.stdout)
        if ledger_path.read_bytes() != ledger_before:
            raise RuntimeError("evidence command mutated the append-only ledger")
        self._verify_product(worktree, product_commit)
        if self._verify_private_source(plan_path) != private_source_commit:
            raise RuntimeError("private evidence source changed during collection")
        if hidden_summary is None:
            raise RuntimeError("hidden-test summary is unavailable")
        hidden_pass = (
            hidden_summary["failed"] == 0
            and hidden_summary["critical_mutants_killed"] is True
            and hidden_summary["noncritical_mutant_kill_rate"] >= 0.8
        )
        if gates["essential-hidden-tests"] is not hidden_pass:
            raise ValueError("hidden-test exit status contradicts its bounded summary")
        gates["essential-hidden-tests"] = hidden_pass
        ledger_attested = ledger_path.read_bytes()
        document = {
            "schema_version": "controller-evidence-attestation-v1.2",
            "protocol_version": "v1.2",
            "task_id": task_id,
            "task_manifest_sha256": task_manifest_sha256,
            "product_commit": product_commit,
            "private_source_commit": private_source_commit,
            "hard_gates": gates,
            "hidden_test_summary": dict(hidden_summary),
            "ledger_prefix_sha256": _sha(ledger_attested),
            "command_evidence": command_evidence,
        }
        self._atomic_json(output_path, document)
        return output_path

    @staticmethod
    def _load_plan(path: Path, task_id: str) -> Mapping[str, Any]:
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, Mapping) or set(value) != {
            "schema_version", "task_id", "commands",
        }:
            raise ValueError("private evidence plan shape is invalid")
        commands = value.get("commands")
        if not all((
            value.get("schema_version") == "controller-evidence-plan-v1.2",
            value.get("task_id") == task_id,
            isinstance(commands, Mapping),
            set(commands or {}) == COMMAND_KINDS,
        )):
            raise ValueError("private evidence plan identity is invalid")
        for command in commands.values():
            if (
                not isinstance(command, Mapping)
                or set(command) != {"argv", "timeout_seconds"}
                or not isinstance(command.get("argv"), list)
                or not command["argv"]
                or not all(isinstance(item, str) and item for item in command["argv"])
                or not isinstance(command.get("timeout_seconds"), (int, float))
                or isinstance(command.get("timeout_seconds"), bool)
                or not 0 < command["timeout_seconds"] <= 3600
            ):
                raise ValueError("private evidence command is invalid")
        return value

    def _run_command(
        self, argv: tuple[str, ...], worktree: Path, timeout: float,
    ) -> subprocess.CompletedProcess[bytes]:
        process = subprocess.Popen(
            argv, cwd=worktree, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            env=self._environment(worktree), start_new_session=True,
        )
        try:
            stdout, stderr = process.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            self._kill_process_group(process.pid)
            process.wait()
            raise
        self._kill_process_group(process.pid)
        return subprocess.CompletedProcess(argv, process.returncode, stdout, stderr)

    @staticmethod
    def _sandboxed(argv: tuple[str, ...], denied_root: Path) -> tuple[str, ...]:
        escaped = str(denied_root.resolve()).replace("\\", "\\\\").replace('"', '\\"')
        profile = f'(version 1)(allow default)(deny file-read* (subpath "{escaped}"))'
        return ("/usr/bin/sandbox-exec", "-p", profile, *argv)

    @staticmethod
    def _kill_process_group(pid: int) -> None:
        try:
            os.killpg(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass

    @staticmethod
    def _verify_private_source(plan_path: Path) -> str:
        root = subprocess.run(
            ("git", "-C", str(plan_path.parent), "rev-parse", "--show-toplevel"),
            capture_output=True, text=True, check=False,
        )
        if root.returncode:
            raise RuntimeError("private evidence plan is not in a Git source")
        repository = Path(root.stdout.strip()).resolve()
        relative = plan_path.relative_to(repository).as_posix()
        head = subprocess.run(
            ("git", "-C", str(repository), "rev-parse", "HEAD"),
            capture_output=True, text=True, check=False,
        )
        status = subprocess.run(
            ("git", "-C", str(repository), "status", "--porcelain", "--untracked-files=all"),
            capture_output=True, text=True, check=False,
        )
        committed = subprocess.run(
            ("git", "-C", str(repository), "show", f"HEAD:{relative}"),
            capture_output=True, check=False,
        )
        if (
            head.returncode or status.returncode or status.stdout
            or committed.returncode or committed.stdout != plan_path.read_bytes()
        ):
            raise RuntimeError("private evidence plan is not clean and commit-bound")
        commit = head.stdout.strip()
        if not SHA1.fullmatch(commit):
            raise RuntimeError("private evidence source commit is invalid")
        tracked = subprocess.run(
            ("git", "-C", str(repository), "ls-files", "-z"),
            capture_output=True, check=False,
        )
        if tracked.returncode:
            raise RuntimeError("private evidence source inventory is unavailable")
        for item in tracked.stdout.split(b"\0"):
            if item and (repository / os.fsdecode(item)).is_symlink():
                raise RuntimeError("private evidence source contains a symlink")
        ignored = subprocess.run(
            ("git", "-C", str(repository), "ls-files", "--others", "-i",
             "--exclude-standard", "-z"),
            capture_output=True, check=False,
        )
        if ignored.returncode or ignored.stdout:
            raise RuntimeError("private evidence source contains ignored material")
        return commit

    @staticmethod
    def _argv(
        values: list[str], worktree: Path, ledger: Path, bundle: Path,
        private_source: Path,
    ) -> tuple[str, ...]:
        replacements = {
            "{worktree}": str(worktree), "{ledger}": str(ledger),
            "{bundle}": str(bundle), "{private_source}": str(private_source),
        }
        return tuple(
            value.replace("{private_source}", replacements["{private_source}"])
            if "{private_source}" in value else replacements.get(value, value)
            for value in values
        )

    @staticmethod
    def _environment(worktree: Path) -> Mapping[str, str]:
        return {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8",
            "CI": "true", "BENCHMARK_WORKTREE": str(worktree),
        }

    @staticmethod
    def _hidden_summary(stdout: bytes) -> Mapping[str, Any]:
        value = json.loads(stdout.decode().strip())
        if not isinstance(value, Mapping) or set(value) != HIDDEN_KEYS:
            raise ValueError("hidden-test output is not a bounded summary")
        total, passed, failed = value["total"], value["passed"], value["failed"]
        rate = value["noncritical_mutant_kill_rate"]
        if not all(isinstance(item, int) and not isinstance(item, bool) for item in (total, passed, failed)):
            raise ValueError("hidden-test counts are invalid")
        if total < 1 or passed < 0 or failed < 0 or passed + failed != total:
            raise ValueError("hidden-test counts do not reconcile")
        if not isinstance(value["critical_mutants_killed"], bool):
            raise ValueError("critical mutation result is invalid")
        if not isinstance(rate, (int, float)) or isinstance(rate, bool) or not 0 <= rate <= 1:
            raise ValueError("noncritical mutation rate is invalid")
        return value

    @staticmethod
    def _gate(kind: str) -> str:
        return {
            "build": "build", "typecheck": "typecheck", "ci": "ci",
            "hidden-tests": "essential-hidden-tests", "ledger-validation": "ledger",
        }[kind]

    @staticmethod
    def _verify_product(worktree: Path, product_commit: str) -> None:
        head = subprocess.run(
            ("git", "-C", str(worktree), "rev-parse", "HEAD"),
            capture_output=True, text=True, check=False,
        )
        status = subprocess.run(
            ("git", "-C", str(worktree), "status", "--porcelain", "--untracked-files=all"),
            capture_output=True, text=True, check=False,
        )
        if head.returncode or status.returncode or head.stdout.strip() != product_commit or status.stdout:
            raise RuntimeError("collector product source is not the expected clean commit")

    @staticmethod
    def _atomic_json(path: Path, document: Mapping[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = (json.dumps(document, indent=2, sort_keys=True) + "\n").encode()
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix=f".{path.name}.", delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(payload)
        temporary.replace(path)
