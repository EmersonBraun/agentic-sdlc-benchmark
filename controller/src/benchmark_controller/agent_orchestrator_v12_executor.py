"""Native Agent Orchestrator executor for the frozen v1.2 role topology."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Protocol, Sequence

from .condition_runner import PRE_MERGE_QUALITY_GATES, REQUIRED_QUALITY_GATES
from .v12_native_backend import NativeStepExecution, NativeStepRequest, V12RoleExecutor

SESSION_PATTERN = re.compile(r"spawned session ([A-Za-z0-9_-]+)")
ANSI_PATTERN = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
PLANNER_STEPS = {"requirements", "planning", "decomposition", "documentation", "merge"}
EXECUTOR_STEPS = {"implementation", "local-testing", "pull-request", "ci-qa"}


@dataclass(frozen=True)
class AOCommandResult:
    stdout: str
    stderr: str
    duration_ms: float


class AOTransport(Protocol):
    def run(self, argv: Sequence[str], *, timeout_seconds: float) -> AOCommandResult: ...


class SubprocessAOTransport:
    def run(self, argv: Sequence[str], *, timeout_seconds: float) -> AOCommandResult:
        started = time.monotonic_ns()
        completed = subprocess.run(
            tuple(argv), capture_output=True, text=True, check=False, timeout=timeout_seconds,
        )
        duration_ms = (time.monotonic_ns() - started) / 1_000_000
        if completed.returncode != 0:
            raise RuntimeError(f"Agent Orchestrator command failed: {Path(argv[0]).name} {argv[1]}")
        return AOCommandResult(completed.stdout, completed.stderr, duration_ms)


@dataclass
class _Session:
    session_id: str
    workspace: Path
    kind: str


class AgentOrchestratorV12RoleExecutor:
    """Drive persistent AO planner/worker sessions and preserve their native worktrees."""

    supports_idempotent_replay = True
    enforces_deadline = True

    def __init__(
        self,
        project: str,
        *,
        ao_path: Path = Path("/Applications/Agent Orchestrator.app/Contents/Resources/daemon/ao"),
        transport: AOTransport | None = None,
        evaluator: V12RoleExecutor | None = None,
    ) -> None:
        self.project = project
        self.ao_path = ao_path
        self.transport = transport or SubprocessAOTransport()
        self.evaluator = evaluator
        self._sessions: dict[tuple[str, str], _Session] = {}
        self._cache: dict[tuple[str, str], NativeStepExecution] = {}
        self._config_checked = False
        self._cleanup_failed = False

    def execute(self, request: NativeStepRequest) -> NativeStepExecution:
        if request.role == "independent_evaluator":
            if self.evaluator is None:
                return self._outcome(request, "failed", "independent-evaluator-unavailable")
            return self.evaluator.execute(request)
        semantic_key = (request.run_id, request.step)
        if semantic_key in self._cache:
            return self._cache[semantic_key]
        if self._remaining(request) <= 0:
            return self._outcome(request, "timeout", "controller-deadline-exceeded")
        orchestration_ms = 0.0
        effective_started: int | None = None
        try:
            orchestration_ms += self._verify_config(request)
            kind = "orchestrator" if request.step in PLANNER_STEPS else "worker"
            session, setup_ms, initial_effective_ms = self._ensure_session(request, kind)
            orchestration_ms += setup_ms
            _, sentinel = self._prompt(request)
            existing, capture_ms = self._capture(session, request)
            orchestration_ms += capture_ms
            effective_started = time.monotonic_ns()
            capture, wait_ms = self._wait(session, sentinel, request)
            effective_ms = initial_effective_ms + max(0, self._elapsed(effective_started) - wait_ms)
            orchestration_ms += wait_ms
            self._verify_capture(request, session, capture, sentinel)
            metadata = self._metadata(request, capture, sentinel, session)
            orchestration_ms += self._synchronize_product_workspace(session, request)
            if self._remaining(request) <= 0:
                raise subprocess.TimeoutExpired("ao", 0)
            orchestration_ms += self._stop_session(request, request.step)
            result = NativeStepExecution(
                status="completed", role=request.role, provider=request.provider, model=request.model,
                workspace=request.worktree, effective_work_ms=effective_ms, external_wait_ms=0,
                orchestration_overhead_ms=orchestration_ms, token_cost_accounting_observed=False,
                tokens={"input": 0, "output": 0, "cached": 0, "reasoning": 0}, cost_usd=0,
                metadata=metadata, completion_proof=metadata.get("completion_proof"),
            )
        except subprocess.TimeoutExpired:
            result = self._outcome(
                request, "timeout", "controller-deadline-exceeded",
                effective_work_ms=self._elapsed(effective_started),
                orchestration_overhead_ms=orchestration_ms,
            )
        except RuntimeError as exc:
            self._discard_session(request.run_id, request.step if "kind" in locals() else None)
            result = self._outcome(
                request, "retry", self._runtime_reason(exc), effective_work_ms=self._elapsed(effective_started),
                orchestration_overhead_ms=orchestration_ms,
            )
        if result.status == "completed":
            self._cache[semantic_key] = result
        return result

    def _discard_session(self, run_id: str, step: str | None) -> None:
        if step is None:
            return
        key = (run_id, step)
        session = self._sessions.get(key)
        if session is None:
            return
        try:
            self.transport.run((
                str(self.ao_path), "session", "kill", session.session_id,
                "--project", self.project,
            ), timeout_seconds=30)
            self.transport.run((
                str(self.ao_path), "session", "cleanup", "--project", self.project, "--yes",
            ), timeout_seconds=60)
            self._sessions.pop(key, None)
        except Exception:
            self._cleanup_failed = True

    @staticmethod
    def _runtime_reason(exc: RuntimeError) -> str:
        message = str(exc)
        if "exited" in message or "command failed" in message:
            return "native-session-exited"
        if "base commit" in message:
            return "delegated-base-mismatch"
        if "JSON" in message:
            return "invalid-native-output"
        return "native-runtime-error"

    def close(self) -> None:
        failed = self._cleanup_failed
        for key, session in tuple(self._sessions.items())[::-1]:
            killed = False
            for _ in range(3):
                try:
                    self.transport.run((
                        str(self.ao_path), "session", "kill", session.session_id,
                        "--project", self.project,
                    ), timeout_seconds=30)
                except Exception:
                    continue
                killed = True
                self._sessions.pop(key, None)
                break
            failed = failed or not killed
        try:
            self.transport.run((
                str(self.ao_path), "session", "cleanup", "--project", self.project, "--yes",
            ), timeout_seconds=60)
        except Exception:
            failed = True
        evaluator_close = getattr(self.evaluator, "close", None)
        if callable(evaluator_close):
            try:
                evaluator_close()
            except Exception:
                failed = True
        if failed:
            raise RuntimeError("Agent Orchestrator terminal cleanup failed")

    def _verify_config(self, request: NativeStepRequest) -> float:
        if self._config_checked:
            return 0
        result = self.transport.run((
            str(self.ao_path), "project", "get", self.project, "--json",
        ), timeout_seconds=self._timeout(request, cap=30))
        try:
            config = json.loads(result.stdout)["project"]["config"]
        except (KeyError, TypeError, json.JSONDecodeError) as exc:
            raise RuntimeError("AO project config is invalid") from exc
        worker = config.get("worker", {})
        orchestrator = config.get("orchestrator", {})
        if not all((
            worker.get("agent") == "grok",
            worker.get("agentConfig", {}).get("model") == "grok-4.5",
            orchestrator.get("agent") == "codex",
            orchestrator.get("agentConfig", {}).get("model") == "gpt-5.4",
        )):
            raise RuntimeError("AO role topology is not frozen")
        self._config_checked = True
        return result.duration_ms

    def _ensure_session(
        self, request: NativeStepRequest, kind: str,
    ) -> tuple[_Session, float, float]:
        key = (request.run_id, request.step)
        if key in self._sessions:
            return self._sessions[key], 0, 0
        preparation_ms = 0.0
        if kind == "orchestrator":
            expected = self.transport.run(
                ("git", "-C", str(request.worktree), "rev-parse", "HEAD"),
                timeout_seconds=self._timeout(request, cap=10),
            )
            aligned = self.transport.run((
                "git", "-C", str(request.worktree), "branch", "-f",
                f"ao/{self.project}-orchestrator", expected.stdout.strip(),
            ), timeout_seconds=self._timeout(request, cap=10))
            preparation_ms += expected.duration_ms + aligned.duration_ms
        prompt, _ = self._prompt(request)
        command = [
            str(self.ao_path), "spawn", "--project", self.project,
            "--name", ("v12-" + kind[:4] + "-" + hashlib.sha256(
                f"{request.run_id}:{request.step}".encode()
            ).hexdigest()[:8])[:20],
            "--issue", "18", "--prompt", prompt, "--kind", kind, "--mode", "tui",
        ]
        # AO owns a persistent shared worktree for orchestrators. Supplying a
        # branch there currently breaks Codex TUI bootstrap; workers remain
        # isolated on a stage-specific branch.
        if kind == "worker":
            branch = f"benchmark/{request.run_id}-{request.step}"
            expected = self.transport.run(
                ("git", "-C", str(request.worktree), "rev-parse", "HEAD"),
                timeout_seconds=self._timeout(request, cap=10),
            )
            aligned = self.transport.run((
                "git", "-C", str(request.worktree), "branch", "-f", branch,
                expected.stdout.strip(),
            ), timeout_seconds=self._timeout(request, cap=10))
            preparation_ms += expected.duration_ms + aligned.duration_ms
            command.extend(("--branch", branch))
        result = self.transport.run(tuple(command), timeout_seconds=self._timeout(request, cap=60))
        match = SESSION_PATTERN.search(result.stdout + result.stderr)
        if not match:
            raise RuntimeError("AO returned no session id")
        session_id = match.group(1)
        try:
            session = self._inspect_session(session_id, kind, request)
        except Exception:
            # A spawn can return success even when the TUI bootstrap exits.
            # Reclaim that partial session so a retry cannot reuse it by name.
            try:
                self.transport.run((
                    str(self.ao_path), "session", "kill", session_id,
                    "--project", self.project,
                ), timeout_seconds=self._timeout(request, cap=30))
            finally:
                self.transport.run((
                    str(self.ao_path), "session", "cleanup", "--project", self.project, "--yes",
                ), timeout_seconds=self._timeout(request, cap=60))
            raise
        self._sessions[key] = session
        return session, preparation_ms, result.duration_ms

    def _stop_session(self, request: NativeStepRequest, step: str) -> float:
        key = (request.run_id, step)
        session = self._sessions[key]
        killed = self.transport.run((
            str(self.ao_path), "session", "kill", session.session_id,
            "--project", self.project,
        ), timeout_seconds=30)
        cleaned = self.transport.run((
            str(self.ao_path), "session", "cleanup", "--project", self.project, "--yes",
        ), timeout_seconds=60)
        self._sessions.pop(key, None)
        return killed.duration_ms + cleaned.duration_ms

    def _synchronize_product_workspace(self, session: _Session, request: NativeStepRequest) -> float:
        """Cherry-pick role-owned commits into the controller's measured worktree."""

        if request.step not in {"implementation", "documentation"}:
            return 0
        status = self.transport.run(
            ("git", "-C", str(session.workspace), "status", "--porcelain"),
            timeout_seconds=self._timeout(request, cap=10),
        )
        if status.stdout.strip():
            raise RuntimeError("AO stage left uncommitted product changes")
        source = self.transport.run(
            ("git", "-C", str(session.workspace), "rev-parse", "HEAD"),
            timeout_seconds=self._timeout(request, cap=10),
        )
        target = self.transport.run(
            ("git", "-C", str(request.worktree), "rev-parse", "HEAD"),
            timeout_seconds=self._timeout(request, cap=10),
        )
        duration = status.duration_ms + source.duration_ms + target.duration_ms
        if source.stdout.strip() == target.stdout.strip():
            raise RuntimeError("AO mutating stage produced no committed change")
        picked = self.transport.run(
            ("git", "-C", str(request.worktree), "cherry-pick", source.stdout.strip()),
            timeout_seconds=self._timeout(request, cap=60),
        )
        return duration + picked.duration_ms

    def _inspect_session(self, session_id: str, kind: str, request: NativeStepRequest) -> _Session:
        result = self.transport.run((
            str(self.ao_path), "session", "get", session_id, "--project", self.project, "--json",
        ), timeout_seconds=self._timeout(request, cap=30))
        try:
            payload = json.loads(result.stdout)["session"]
            raw_workspace = payload.get("workspacePath") or payload.get("workspace_path")
        except (KeyError, TypeError, json.JSONDecodeError) as exc:
            raise RuntimeError("AO session metadata is invalid") from exc
        if payload.get("status") == "exited" or payload.get("activity", {}).get("state") == "exited":
            raise RuntimeError("AO session exited during TUI bootstrap")
        if raw_workspace:
            workspace = Path(str(raw_workspace)).resolve()
        elif kind == "orchestrator":
            workspace = (
                Path.home() / ".ao" / "data" / "worktrees" / self.project
                / "orchestrator" / f"{self.project}-orchestrator"
            ).resolve()
        else:
            workspace = (
                Path.home() / ".ao" / "data" / "worktrees" / self.project / session_id
            ).resolve()
        if not workspace.is_dir():
            raise RuntimeError("AO delegated workspace is missing")
        head = self.transport.run(
            ("git", "-C", str(workspace), "rev-parse", "HEAD"),
            timeout_seconds=self._timeout(request, cap=10),
        ).stdout.strip()
        expected = self.transport.run(
            ("git", "-C", str(request.worktree), "rev-parse", "HEAD"),
            timeout_seconds=self._timeout(request, cap=10),
        ).stdout.strip()
        if head != expected:
            raise RuntimeError("AO delegated workspace base commit mismatch")
        return _Session(session_id, workspace, kind)

    def _capture(self, session: _Session, request: NativeStepRequest) -> tuple[str, float]:
        result = self.transport.run(
            ("tmux", "capture-pane", "-pt", session.session_id, "-S", "-1000"),
            timeout_seconds=self._timeout(request, cap=10),
        )
        return ANSI_PATTERN.sub("", result.stdout + result.stderr), result.duration_ms

    def _wait(self, session: _Session, sentinel: str, request: NativeStepRequest) -> tuple[str, float]:
        waited_ms = 0.0
        while self._remaining(request) > 0:
            capture, duration = self._capture(session, request)
            waited_ms += duration
            if self._stage_occurrences(capture, sentinel) >= 2:
                return capture, waited_ms
            time.sleep(min(0.5, self._remaining(request)))
        raise subprocess.TimeoutExpired("ao", 0)

    @staticmethod
    def _stage_occurrences(capture: str, sentinel: str) -> int:
        return capture.count(sentinel)

    @staticmethod
    def _verify_capture(
        request: NativeStepRequest, session: _Session, capture: str, sentinel: str,
    ) -> None:
        expected_model = "gpt-5.4" if request.role == "planner_requirements_lead" else "grok 4.5"
        if (
            AgentOrchestratorV12RoleExecutor._stage_occurrences(capture, sentinel) < 2
            or expected_model.lower() not in capture.lower()
        ):
            raise RuntimeError("AO model identity or completion sentinel was not observed")
        if "Do you trust the contents" in capture:
            raise RuntimeError("AO trust prompt blocked autonomous execution")

    @classmethod
    def _prompt(cls, request: NativeStepRequest) -> tuple[str, str]:
        sentinel = cls._sentinel(request)
        task = request.task_path.read_text(encoding="utf-8")
        handoff = request.handoff_path.read_text(encoding="utf-8") if request.handoff_path else ""
        factor = request.agentskit_context_path.read_text(encoding="utf-8") if request.agentskit_context_path else ""
        rules = (
            f"SDLC stage {request.step}. Work autonomously only in the current AO worktree. "
            f"Finish with {sentinel}."
        )
        if request.step in {"requirements", "planning", "decomposition"}:
            rules += " Do not call tools; all admissible inputs are supplied."
        if request.step == "decomposition":
            rules += " Return JSON with handoff_payload containing requirements, implementation_plan, acceptance_criteria."
        if request.step == "implementation":
            rules += (
                " State the supplied handoff and AgentsKit SHA-256 digests verbatim. "
                "Commit all product changes before the sentinel and leave the worktree clean."
            )
        if request.step == "documentation":
            rules += " Commit all documentation changes before the sentinel and leave the worktree clean."
        if request.step == "review":
            rules += (
                " Return JSON with completion_proof containing verified_gates and "
                "product_quality_score. The only allowed gates are: "
                + ", ".join(sorted(PRE_MERGE_QUALITY_GATES)) + "."
            )
        if request.step == "merge":
            rules += (
                " Return JSON with completion_proof containing verified_gates, "
                "product_quality_score, and the exact 40-character merge_commit. The only "
                "allowed gates are: " + ", ".join(sorted(REQUIRED_QUALITY_GATES)) + "."
            )
        return "\n\n".join((rules, "TASK:\n" + task, "HANDOFF:\n" + handoff, "AGENTSKIT:\n" + factor)), sentinel

    @classmethod
    def _metadata(
        cls, request: NativeStepRequest, capture: str, sentinel: str, session: _Session,
    ) -> dict[str, Any]:
        metadata: dict[str, Any] = {
            "sentinel_sha256": hashlib.sha256(sentinel.encode()).hexdigest(),
            "delegated_workspace_sha256": hashlib.sha256(str(session.workspace).encode()).hexdigest(),
            "raw_output_persisted": False,
            "usage_observation": {"token_breakdown_observed": False, "zero_tokens_mean_unavailable": True},
        }
        if request.step == "decomposition":
            metadata["handoff_payload"] = cls._extract_json(capture, "handoff_payload")["handoff_payload"]
        if request.step in {"review", "merge"}:
            proof = cls._extract_json(capture, "completion_proof").get("completion_proof")
            if not isinstance(proof, Mapping):
                raise RuntimeError("AO stage output omitted completion proof")
            metadata["completion_proof"] = dict(proof)
        if request.handoff_path:
            digest = hashlib.sha256(request.handoff_path.read_bytes()).hexdigest()
            if digest not in capture:
                raise RuntimeError("AO executor did not acknowledge the handoff digest")
            metadata["handoff_sha256_observed"] = digest
        if request.agentskit_context_path:
            digest = hashlib.sha256(request.agentskit_context_path.read_bytes()).hexdigest()
            if digest not in capture:
                raise RuntimeError("AO role did not acknowledge the AgentsKit digest")
            metadata["agentskit_context_sha256_observed"] = digest
            metadata["agentskit_components_observed"] = ["doc-bridge", "playbook", "code-review"]
        return metadata

    @staticmethod
    def _extract_json(text: str, key: str) -> Mapping[str, Any]:
        decoder = json.JSONDecoder()
        for index, character in enumerate(text):
            if character != "{":
                continue
            try:
                value, _ = decoder.raw_decode(text[index:])
            except json.JSONDecodeError:
                continue
            if isinstance(value, Mapping) and key in value:
                return value
        raise RuntimeError("AO output omitted required JSON")

    @staticmethod
    def _sentinel(request: NativeStepRequest) -> str:
        return "V12_AO_" + hashlib.sha256(f"{request.run_id}:{request.step}".encode()).hexdigest()[:20].upper()

    @staticmethod
    def _remaining(request: NativeStepRequest) -> float:
        if request.deadline_epoch_ms is None:
            return 900
        return max(0, (request.deadline_epoch_ms - time.time() * 1000) / 1000)

    @classmethod
    def _timeout(cls, request: NativeStepRequest, *, cap: float) -> float:
        remaining = cls._remaining(request)
        if remaining <= 0:
            raise subprocess.TimeoutExpired("ao", 0)
        return min(remaining, cap)

    @staticmethod
    def _elapsed(started: int | None) -> float:
        return 0 if started is None else (time.monotonic_ns() - started) / 1_000_000

    @staticmethod
    def _outcome(
        request: NativeStepRequest, status: str, reason: str, *,
        effective_work_ms: float = 0, orchestration_overhead_ms: float = 0,
    ) -> NativeStepExecution:
        return NativeStepExecution(
            status=status, role=request.role, provider=request.provider, model=request.model,
            workspace=request.worktree, effective_work_ms=max(0, effective_work_ms), external_wait_ms=0,
            orchestration_overhead_ms=max(0, orchestration_overhead_ms),
            token_cost_accounting_observed=False,
            tokens={"input": 0, "output": 0, "cached": 0, "reasoning": 0}, cost_usd=0,
            metadata={}, reason=reason,
        )
