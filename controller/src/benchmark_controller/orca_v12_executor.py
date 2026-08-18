"""Native ORCA executor for the frozen v1.2 role topology."""

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

EXPECTED_ORCA_VERSION = "1.4.184"
PLANNER_STEPS = {"requirements", "planning", "decomposition", "documentation", "merge"}
MUTATING_STEPS = {"implementation", "local-testing", "pull-request", "ci-qa", "documentation", "merge"}


@dataclass(frozen=True)
class OrcaCommandResult:
    value: Mapping[str, Any]
    duration_ms: float


class OrcaTransport(Protocol):
    def run_json(self, argv: Sequence[str], *, timeout_seconds: float) -> OrcaCommandResult: ...


class SubprocessOrcaTransport:
    def __init__(self, executable: Path = Path("/usr/local/bin/orca")) -> None:
        self.executable = executable

    def run_json(self, argv: Sequence[str], *, timeout_seconds: float) -> OrcaCommandResult:
        started = time.monotonic_ns()
        completed = subprocess.run(
            (str(self.executable), *argv), capture_output=True, text=True,
            check=False, timeout=timeout_seconds,
        )
        duration_ms = (time.monotonic_ns() - started) / 1_000_000
        try:
            value = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"ORCA returned invalid JSON: {argv[0]}") from exc
        if not isinstance(value, Mapping) or value.get("ok") is not True or completed.returncode != 0:
            code = value.get("error", {}).get("code") if isinstance(value, Mapping) else None
            raise RuntimeError(f"ORCA command failed: {argv[0]}:{code or 'unknown'}")
        return OrcaCommandResult(value, duration_ms)


@dataclass
class _Run:
    run_id: str
    coordinator: str
    workspace: Path


class OrcaV12RoleExecutor:
    """Execute capability-bound ORCA Dispatches in the measured product worktree."""

    supports_idempotent_replay = True
    enforces_deadline = True

    def __init__(
        self, *, transport: OrcaTransport | None = None,
        evaluator: V12RoleExecutor | None = None, stable_idle_seconds: float = 15,
    ) -> None:
        self.transport = transport or SubprocessOrcaTransport()
        self.evaluator = evaluator
        self.stable_idle_seconds = stable_idle_seconds
        self._runs: dict[str, _Run] = {}
        self._workers: dict[tuple[str, str], str] = {}
        self._orphaned_terminals: set[str] = set()
        self._cache: dict[tuple[str, str], NativeStepExecution] = {}
        self._preflight_checked = False

    def execute(self, request: NativeStepRequest) -> NativeStepExecution:
        if request.role == "independent_evaluator":
            if self.evaluator is None:
                return self._outcome(request, "retry", "independent-evaluator-unavailable")
            return self.evaluator.execute(request)
        key = (request.run_id, request.step)
        if key in self._cache:
            return self._cache[key]
        if self._remaining(request) <= 0:
            return self._outcome(request, "timeout", "controller-deadline-exceeded")

        overhead_ms = 0.0
        effective_ms = 0.0
        external_wait_ms = 0.0
        effective_started: int | None = None
        polling_ms = 0.0
        polling_clock = [0.0]
        dispatch_started = False
        starting_head: str | None = None
        try:
            overhead_ms += self._preflight(request)
            run, created_ms = self._run(request)
            overhead_ms += created_ms
            overhead_ms += self._validate_clean_worktree(request)
            if request.step == "implementation":
                starting_head, head_ms = self._git_head(request)
                overhead_ms += head_ms
            prompt, sentinel = self._prompt(request)
            task_id, task_ms = self._create_task(run, request, prompt)
            overhead_ms += task_ms
            worker, worker_ms = self._create_ready_worker(run, request)
            overhead_ms += worker_ms
            self._workers[key] = worker
            capture_cursor, cursor_ms = self._capture_cursor(worker, request)
            overhead_ms += cursor_ms
            dispatch_started = True
            dispatch_id, dispatch_ms = self._dispatch(run, task_id, worker, request)
            overhead_ms += dispatch_ms
            effective_started = time.monotonic_ns()
            dispatch, polling_ms = self._await_dispatch(task_id, worker, request, polling_clock)
            effective_ms = max(0, self._elapsed(effective_started) - polling_ms)
            effective_started = None
            overhead_ms += polling_ms
            delivery, delivery_ms = self._settle_delivery(run, task_id, dispatch_id, request)
            overhead_ms += delivery_ms
            output_wait = self.transport.run_json((
                "terminal", "wait", "--terminal", worker, "--for", "tui-idle",
                "--timeout-ms", str(int(self._timeout(request, 60) * 1000)), "--json",
            ), timeout_seconds=self._timeout(request, 65))
            overhead_ms += output_wait.duration_ms
            capture, capture_ms = self._read_terminal(worker, capture_cursor, request)
            overhead_ms += capture_ms
            durable_output = "\n".join(str(delivery.get(key, "")) for key in ("subject", "body"))
            self._verify(request, dispatch, delivery, capture, durable_output, sentinel)
            metadata = self._metadata(request, dispatch, durable_output, sentinel)
            overhead_ms += self._validate_merge_binding(request, metadata)
            overhead_ms += self._validate_clean_worktree(request)
            if starting_head is not None:
                ending_head, head_ms = self._git_head(request)
                overhead_ms += head_ms
                if ending_head == starting_head:
                    raise RuntimeError("ORCA implementation produced no committed product delta")
            if self._remaining(request) <= 0:
                raise subprocess.TimeoutExpired("orca", 0)
            overhead_ms += self._close_worker(key, request)
            result = NativeStepExecution(
                status="completed", role=request.role, provider=request.provider, model=request.model,
                workspace=request.worktree, effective_work_ms=effective_ms,
                external_wait_ms=external_wait_ms, orchestration_overhead_ms=overhead_ms,
                token_cost_accounting_observed=False,
                tokens={"input": 0, "output": 0, "cached": 0, "reasoning": 0}, cost_usd=0,
                metadata=metadata, completion_proof=metadata.get("completion_proof"),
            )
        except subprocess.TimeoutExpired:
            polling_ms = polling_clock[0]
            if effective_started is not None:
                effective_ms += max(0, self._elapsed(effective_started) - polling_ms)
                overhead_ms += polling_ms
            result = self._outcome(
                request, "failed" if dispatch_started else "timeout",
                "post-dispatch-evidence-incomplete" if dispatch_started else "controller-deadline-exceeded",
                effective_work_ms=effective_ms, external_wait_ms=external_wait_ms,
                orchestration_overhead_ms=overhead_ms,
            )
            self._discard_worker(key, request)
        except RuntimeError as exc:
            polling_ms = polling_clock[0]
            if effective_started is not None:
                effective_ms += max(0, self._elapsed(effective_started) - polling_ms)
                overhead_ms += polling_ms
            self._discard_worker(key, request)
            result = self._outcome(
                request, "failed" if dispatch_started else "retry",
                "post-dispatch-evidence-invalid" if dispatch_started else self._reason(exc),
                effective_work_ms=effective_ms,
                external_wait_ms=external_wait_ms, orchestration_overhead_ms=overhead_ms,
            )
        if result.status == "completed":
            self._cache[key] = result
        return result

    def close(self) -> None:
        failed = False
        for key in tuple(self._workers):
            try:
                self._close_worker_unbounded(key)
            except Exception:
                failed = True
        for worker in tuple(self._orphaned_terminals):
            try:
                self._close_terminal(worker)
                self._orphaned_terminals.discard(worker)
            except Exception:
                failed = True
        for run_id, run in tuple(self._runs.items()):
            try:
                self._close_terminal(run.coordinator)
                self._runs.pop(run_id, None)
            except Exception:
                failed = True
        evaluator_close = getattr(self.evaluator, "close", None)
        if callable(evaluator_close):
            try:
                evaluator_close()
            except Exception:
                failed = True
        if failed:
            raise RuntimeError("ORCA terminal cleanup failed")

    def _preflight(self, request: NativeStepRequest) -> float:
        if self._preflight_checked:
            return 0
        result = self.transport.run_json(("status", "--json"), timeout_seconds=self._timeout(request, 30))
        runtime = self._nested(result.value, "result", "runtime")
        graph = self._nested(result.value, "result", "graph")
        if not isinstance(runtime, Mapping) or not isinstance(graph, Mapping) or not all((
            runtime.get("state") == "ready", graph.get("state") == "ready",
            runtime.get("appVersion") == EXPECTED_ORCA_VERSION,
        )):
            raise RuntimeError("ORCA runtime is not frozen-ready")
        self._preflight_checked = True
        return result.duration_ms

    def _run(self, request: NativeStepRequest) -> tuple[_Run, float]:
        existing = self._runs.get(request.run_id)
        if existing:
            if existing.workspace != request.worktree.resolve():
                raise RuntimeError("ORCA Run workspace mismatch")
            return existing, 0
        coordinator = self.transport.run_json((
            "terminal", "create", "--worktree", f"path:{request.worktree.resolve()}",
            "--title", "v12-orca-coordinator", "--command", "zsh", "--json",
        ), timeout_seconds=self._timeout(request, 60))
        handle = self._nested(coordinator.value, "result", "terminal", "handle")
        if not isinstance(handle, str):
            raise RuntimeError("ORCA coordinator identity missing")
        self._orphaned_terminals.add(handle)
        try:
            created = self.transport.run_json((
                "orchestration", "run-create", "--objective", f"v1.2 {request.condition_id}",
                "--from", handle, "--json",
            ), timeout_seconds=self._timeout(request, 30))
            run_id = self._nested(created.value, "result", "run", "id")
            if not isinstance(run_id, str):
                raise RuntimeError("ORCA Run identity missing")
        except Exception:
            try:
                self._close_terminal(handle)
                self._orphaned_terminals.discard(handle)
            except Exception:
                pass
            raise
        run = _Run(run_id, handle, request.worktree.resolve())
        self._runs[request.run_id] = run
        self._orphaned_terminals.discard(handle)
        return run, coordinator.duration_ms + created.duration_ms

    def _create_task(self, run: _Run, request: NativeStepRequest, prompt: str) -> tuple[str, float]:
        result = self.transport.run_json((
            "orchestration", "task-create", "--run", run.run_id, "--from", run.coordinator,
            "--task-title", f"v12-{request.step}", "--spec", prompt, "--json",
        ), timeout_seconds=self._timeout(request, 30))
        task_id = self._nested(result.value, "result", "task", "id")
        if not isinstance(task_id, str):
            raise RuntimeError("ORCA task identity missing")
        return task_id, result.duration_ms

    def _create_ready_worker(self, run: _Run, request: NativeStepRequest) -> tuple[str, float]:
        command = (
            "codex --model gpt-5.4 --ask-for-approval never"
            if request.step in PLANNER_STEPS else
            "grok --model grok-4.5 --reasoning-effort high --always-approve"
        )
        created = self.transport.run_json((
            "terminal", "create", "--worktree", f"path:{run.workspace}",
            "--title", f"v12-{request.step}", "--command", command, "--json",
        ), timeout_seconds=self._timeout(request, 60))
        handle = self._nested(created.value, "result", "terminal", "handle")
        if not isinstance(handle, str):
            raise RuntimeError("ORCA worker identity missing")
        duration = created.duration_ms
        try:
            for _ in range(2):
                waited = self.transport.run_json((
                    "terminal", "wait", "--terminal", handle, "--for", "tui-idle",
                    "--timeout-ms", str(int(self._timeout(request, 120) * 1000)), "--json",
                ), timeout_seconds=self._timeout(request, 125))
                duration += waited.duration_ms
                state = self._nested(waited.value, "result", "wait")
                if not isinstance(state, Mapping) or state.get("satisfied") is not True:
                    raise RuntimeError("ORCA worker TUI did not become ready")
                if _ == 0:
                    stable_sleep = min(self.stable_idle_seconds, self._remaining(request))
                    time.sleep(stable_sleep)
        except Exception:
            self._close_terminal(handle)
            raise
        return handle, duration + stable_sleep * 1000

    def _dispatch(
        self, run: _Run, task_id: str, worker: str, request: NativeStepRequest,
    ) -> tuple[str, float]:
        result = self.transport.run_json((
            "orchestration", "dispatch", "--run", run.run_id, "--task", task_id, "--to", worker,
            "--from", run.coordinator, "--inject", "--json",
        ), timeout_seconds=self._timeout(request, 30))
        dispatch_id = self._nested(result.value, "result", "dispatch", "id")
        if not isinstance(dispatch_id, str):
            raise RuntimeError("ORCA Dispatch identity missing")
        return dispatch_id, result.duration_ms

    def _await_dispatch(
        self, task_id: str, worker: str, request: NativeStepRequest,
        polling_clock: list[float],
    ) -> tuple[Mapping[str, Any], float]:
        command_ms = 0.0
        while self._remaining(request) > 0:
            shown = self.transport.run_json((
                "orchestration", "dispatch-show", "--task", task_id, "--json",
            ), timeout_seconds=self._timeout(request, 15))
            command_ms += shown.duration_ms
            polling_clock[0] = command_ms
            dispatch = self._nested(shown.value, "result", "dispatch")
            if isinstance(dispatch, Mapping) and dispatch.get("status") in {"completed", "failed"}:
                if dispatch.get("status") != "completed":
                    raise RuntimeError("ORCA Dispatch failed")
                return dispatch, command_ms
            terminal = self.transport.run_json((
                "terminal", "show", "--terminal", worker, "--json",
            ), timeout_seconds=self._timeout(request, 15))
            command_ms += terminal.duration_ms
            polling_clock[0] = command_ms
            if self._nested(terminal.value, "result", "terminal", "connected") is False:
                raise RuntimeError("ORCA worker disconnected")
            time.sleep(min(0.5, self._remaining(request)))
        raise subprocess.TimeoutExpired("orca", 0)

    def _settle_delivery(
        self, run: _Run, task_id: str, dispatch_id: str, request: NativeStepRequest,
    ) -> tuple[Mapping[str, Any], float]:
        checked = self.transport.run_json((
            "orchestration", "check", "--run", run.run_id, "--terminal", run.coordinator,
            "--types", "worker_done", "--json",
        ), timeout_seconds=self._timeout(request, 30))
        messages = self._nested(checked.value, "result", "messages")
        delivery_id = self._nested(checked.value, "result", "deliveryId")
        matched: Mapping[str, Any] | None = None
        match_count = 0
        if isinstance(messages, list):
            for message in messages:
                if not isinstance(message, Mapping) or message.get("type") != "worker_done":
                    continue
                try:
                    payload = json.loads(str(message.get("payload", "{}")))
                except json.JSONDecodeError:
                    continue
                if (
                    payload.get("taskId") == task_id
                    and payload.get("dispatchId") == dispatch_id
                    and payload.get("outcome") == "succeeded"
                ):
                    matched = message
                    match_count += 1
        if (
            matched is None or match_count != 1 or not isinstance(delivery_id, str)
            or not isinstance(messages, list) or len(messages) != 1
        ):
            raise RuntimeError("ORCA worker_done delivery missing")
        ack = self.transport.run_json((
            "orchestration", "check", "--run", run.run_id, "--terminal", run.coordinator,
            "--ack", delivery_id, "--json",
        ), timeout_seconds=self._timeout(request, 30))
        return matched, checked.duration_ms + ack.duration_ms

    def _capture_cursor(self, worker: str, request: NativeStepRequest) -> tuple[int, float]:
        result = self.transport.run_json((
            "terminal", "read", "--terminal", worker, "--limit", "1", "--json",
        ), timeout_seconds=self._timeout(request, 30))
        terminal = self._nested(result.value, "result", "terminal")
        raw_cursor = terminal.get("nextCursor") if isinstance(terminal, Mapping) else None
        try:
            cursor = int(str(raw_cursor))
        except (TypeError, ValueError):
            raise RuntimeError("ORCA terminal cursor missing")
        return cursor, result.duration_ms

    def _read_terminal(
        self, worker: str, cursor: int, request: NativeStepRequest,
    ) -> tuple[str, float]:
        chunks: list[str] = []
        duration = 0.0
        while True:
            result = self.transport.run_json((
                "terminal", "read", "--terminal", worker, "--cursor", str(cursor),
                "--limit", "1000", "--json",
            ), timeout_seconds=self._timeout(request, 30))
            duration += result.duration_ms
            terminal = self._nested(result.value, "result", "terminal")
            if not isinstance(terminal, Mapping) or terminal.get("truncated") is True:
                raise RuntimeError("ORCA terminal output was truncated")
            for key in ("output", "text", "content", "lines", "tail"):
                value = terminal.get(key)
                if isinstance(value, str):
                    chunks.append(value)
                elif isinstance(value, list):
                    chunks.append("\n".join(
                        str(item.get("text", item)) if isinstance(item, Mapping) else str(item)
                        for item in value
                    ))
            try:
                next_cursor = int(str(terminal.get("nextCursor")))
            except (TypeError, ValueError):
                next_cursor = None
            if terminal.get("limited") is not True:
                break
            if not isinstance(next_cursor, int) or next_cursor <= cursor:
                raise RuntimeError("ORCA terminal pagination did not advance")
            cursor = next_cursor
        text = "\n".join(chunks)
        if not text:
            raise RuntimeError("ORCA terminal output missing")
        return text, duration

    def _verify(
        self, request: NativeStepRequest, dispatch: Mapping[str, Any],
        delivery: Mapping[str, Any], capture: str, durable_output: str, sentinel: str,
    ) -> None:
        model_pattern = r"model:\s*gpt-5\.4" if request.step in PLANNER_STEPS else r"grok\s+4\.5"
        if sentinel not in durable_output or re.search(model_pattern, capture, re.IGNORECASE) is None:
            raise RuntimeError("ORCA model identity or completion sentinel missing")
        if request.step == "decomposition":
            self._extract_json(durable_output, "handoff_payload")
        if request.step in {"review", "merge"}:
            self._extract_json(durable_output, "completion_proof")
        if not all((
            dispatch.get("failure_count") == 0,
            isinstance(dispatch.get("capability_hash"), str),
            bool(dispatch.get("capability_revoked_at")),
            delivery.get("type") == "worker_done",
        )):
            raise RuntimeError("ORCA settlement invariants failed")

    def _metadata(
        self, request: NativeStepRequest, dispatch: Mapping[str, Any], durable_output: str, sentinel: str,
    ) -> dict[str, Any]:
        metadata: dict[str, Any] = {
            "sentinel_sha256": hashlib.sha256(sentinel.encode()).hexdigest(),
            "dispatch_id_sha256": hashlib.sha256(str(dispatch.get("id", "")).encode()).hexdigest(),
            "capability_hash_observed": bool(dispatch.get("capability_hash")),
            "raw_output_persisted": False,
            "usage_observation": {"token_breakdown_observed": False, "zero_tokens_mean_unavailable": True},
        }
        if request.step == "decomposition":
            metadata["handoff_payload"] = self._extract_json(durable_output, "handoff_payload")["handoff_payload"]
        if request.step in {"review", "merge"}:
            proof = self._extract_json(durable_output, "completion_proof").get("completion_proof")
            if not isinstance(proof, Mapping):
                raise RuntimeError("ORCA completion proof missing")
            metadata["completion_proof"] = dict(proof)
        for path, key, label in (
            (request.handoff_path, "handoff_sha256_observed", "handoff"),
            (request.agentskit_context_path, "agentskit_context_sha256_observed", "AgentsKit"),
        ):
            if path:
                digest = hashlib.sha256(path.read_bytes()).hexdigest()
                if digest not in durable_output:
                    raise RuntimeError(f"ORCA worker did not acknowledge {label} digest")
                metadata[key] = digest
        if request.agentskit_context_path:
            metadata["agentskit_components_observed"] = ["doc-bridge", "playbook", "code-review"]
        return metadata

    @classmethod
    def _validate_merge_binding(cls, request: NativeStepRequest, metadata: Mapping[str, Any]) -> float:
        if request.step != "merge":
            return 0
        started = time.monotonic_ns()
        completed = subprocess.run(
            ("git", "-C", str(request.worktree), "rev-parse", "HEAD"),
            capture_output=True, text=True, check=False, timeout=cls._timeout(request, 10),
        )
        duration = (time.monotonic_ns() - started) / 1_000_000
        proof = metadata.get("completion_proof")
        merge_commit = proof.get("merge_commit") if isinstance(proof, Mapping) else None
        if completed.returncode != 0 or merge_commit != completed.stdout.strip():
            raise RuntimeError("ORCA merge proof is not bound to the measured product commit")
        return duration

    def _close_worker(self, key: tuple[str, str], request: NativeStepRequest) -> float:
        worker = self._workers[key]
        duration = self._close_terminal(worker, request)
        self._workers.pop(key, None)
        return duration

    def _close_worker_unbounded(self, key: tuple[str, str]) -> None:
        worker = self._workers[key]
        self._close_terminal(worker)
        self._workers.pop(key, None)

    def _discard_worker(
        self, key: tuple[str, str], request: NativeStepRequest | None = None,
    ) -> None:
        if key not in self._workers:
            return
        try:
            if request is None:
                self._close_worker_unbounded(key)
            else:
                self._close_worker(key, request)
        except Exception:
            worker = self._workers.pop(key, None)
            if worker:
                self._orphaned_terminals.add(worker)

    def _close_terminal(self, handle: str, request: NativeStepRequest | None = None) -> float:
        timeout = self._timeout(request, 30) if request else 30
        closed = self.transport.run_json(
            ("terminal", "close", "--terminal", handle, "--json"), timeout_seconds=timeout,
        )
        duration = closed.duration_ms
        for _ in range(20):
            try:
                shown = self.transport.run_json(
                    ("terminal", "show", "--terminal", handle, "--json"),
                    timeout_seconds=self._timeout(request, 10) if request else 10,
                )
            except RuntimeError as exc:
                if "terminal_handle_stale" in str(exc):
                    return duration
                raise
            duration += shown.duration_ms
            if self._nested(shown.value, "result", "terminal", "connected") is False:
                return duration
            time.sleep(0.1)
        raise RuntimeError("ORCA terminal cleanup could not be verified")

    @classmethod
    def _prompt(cls, request: NativeStepRequest) -> tuple[str, str]:
        sentinel = "V12_ORCA_" + hashlib.sha256(
            f"{request.run_id}:{request.step}".encode()
        ).hexdigest()[:20].upper()
        task = request.task_path.read_text(encoding="utf-8")
        handoff = request.handoff_path.read_text(encoding="utf-8") if request.handoff_path else ""
        factor = request.agentskit_context_path.read_text(encoding="utf-8") if request.agentskit_context_path else ""
        handoff_digest = hashlib.sha256(request.handoff_path.read_bytes()).hexdigest() if request.handoff_path else ""
        factor_digest = hashlib.sha256(request.agentskit_context_path.read_bytes()).hexdigest() if request.agentskit_context_path else ""
        rules = (
            f"Execute SDLC stage {request.step} only in the current ORCA worktree. "
            f"Before calling worker_done, print the complete requested output ending with {sentinel}; "
            "only after that output is visible, settle this Dispatch with worker_done exactly once. "
            f"The worker_done body must also repeat the complete compact output and {sentinel} so the "
            "coordinator can verify it from the durable delivery."
        )
        if request.step in {"requirements", "planning", "decomposition"}:
            rules += " Do not inspect or edit files; all admissible inputs follow."
        if request.step == "decomposition":
            rules += " Return JSON with handoff_payload containing requirements, implementation_plan, acceptance_criteria."
        if request.step == "implementation":
            rules += (
                " State the handoff and AgentsKit SHA-256 digests verbatim. Commit all product "
                "changes before completion and leave the worktree clean."
            )
        if request.step in {"local-testing", "pull-request", "ci-qa", "documentation", "merge"}:
            rules += " Commit any product changes before completion and leave the worktree clean."
        if request.step == "review":
            rules += (
                " Return a JSON object with completion_proof containing verified_gates and "
                "product_quality_score, using only gates: "
                + ", ".join(sorted(PRE_MERGE_QUALITY_GATES)) + "."
            )
        if request.step == "merge":
            rules += (
                " Return a JSON object with completion_proof containing verified_gates, "
                "product_quality_score, and exact 40-character merge_commit, using only gates: "
                + ", ".join(sorted(REQUIRED_QUALITY_GATES)) + "."
            )
        return "\n\n".join((
            rules, "TASK:\n" + task,
            "HANDOFF_SHA256:" + handoff_digest + "\nHANDOFF:\n" + handoff,
            "AGENTSKIT_SHA256:" + factor_digest + "\nAGENTSKIT:\n" + factor,
        )), sentinel

    @classmethod
    def _validate_clean_worktree(cls, request: NativeStepRequest) -> float:
        if request.step not in MUTATING_STEPS:
            return 0
        started = time.monotonic_ns()
        completed = subprocess.run(
            ("git", "-C", str(request.worktree), "status", "--porcelain"),
            capture_output=True, text=True, check=False, timeout=cls._timeout(request, 10),
        )
        duration = (time.monotonic_ns() - started) / 1_000_000
        if completed.returncode != 0 or completed.stdout.strip():
            raise RuntimeError("ORCA worker left the measured worktree dirty")
        return duration

    @classmethod
    def _git_head(cls, request: NativeStepRequest) -> tuple[str, float]:
        started = time.monotonic_ns()
        completed = subprocess.run(
            ("git", "-C", str(request.worktree), "rev-parse", "HEAD"),
            capture_output=True, text=True, check=False, timeout=cls._timeout(request, 10),
        )
        duration = (time.monotonic_ns() - started) / 1_000_000
        head = completed.stdout.strip()
        if completed.returncode != 0 or len(head) != 40:
            raise RuntimeError("ORCA measured product HEAD is unavailable")
        return head, duration

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
        raise RuntimeError("ORCA output omitted required JSON")

    @staticmethod
    def _nested(value: Mapping[str, Any], *keys: str) -> Any:
        current: Any = value
        for key in keys:
            if not isinstance(current, Mapping):
                return None
            current = current.get(key)
        return current

    @staticmethod
    def _reason(exc: RuntimeError) -> str:
        message = str(exc)
        if "JSON" in message or "output" in message:
            return "invalid-native-output"
        if "settlement" in message or "worker_done" in message:
            return "native-settlement-failed"
        if "workspace" in message:
            return "native-workspace-boundary-mismatch"
        return "native-runtime-error"

    @staticmethod
    def _remaining(request: NativeStepRequest) -> float:
        if request.deadline_epoch_ms is None:
            return 900
        return max(0, (request.deadline_epoch_ms - time.time() * 1000) / 1000)

    @classmethod
    def _timeout(cls, request: NativeStepRequest, cap: float) -> float:
        remaining = cls._remaining(request)
        if remaining <= 0:
            raise subprocess.TimeoutExpired("orca", 0)
        return min(remaining, cap)

    @staticmethod
    def _elapsed(started: int | None) -> float:
        return 0 if started is None else (time.monotonic_ns() - started) / 1_000_000

    @staticmethod
    def _outcome(
        request: NativeStepRequest, status: str, reason: str, *,
        effective_work_ms: float = 0, external_wait_ms: float = 0,
        orchestration_overhead_ms: float = 0,
    ) -> NativeStepExecution:
        return NativeStepExecution(
            status=status, role=request.role, provider=request.provider, model=request.model,
            workspace=request.worktree, effective_work_ms=max(0, effective_work_ms),
            external_wait_ms=max(0, external_wait_ms),
            orchestration_overhead_ms=max(0, orchestration_overhead_ms),
            token_cost_accounting_observed=False,
            tokens={"input": 0, "output": 0, "cached": 0, "reasoning": 0}, cost_usd=0,
            metadata={}, reason=reason,
        )
