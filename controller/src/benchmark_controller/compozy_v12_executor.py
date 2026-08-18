"""Concrete Compozy transport for the frozen v1.2 Codex/Grok role topology."""

from __future__ import annotations

import hashlib
import json
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Protocol, Sequence

from .compozy_grok import validate_provider_config
from .condition_runner import PRE_MERGE_QUALITY_GATES, REQUIRED_QUALITY_GATES
from .v12_native_backend import NativeStepExecution, NativeStepRequest


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


@dataclass(frozen=True)
class CommandResult:
    value: Any
    duration_ms: float


class CompozyTransport(Protocol):
    def run_json(self, argv: Sequence[str], *, timeout_seconds: float) -> CommandResult: ...


class SubprocessCompozyTransport:
    """Run bounded Compozy JSON commands without publishing prompt or output content."""

    def __init__(self, executable: str = "compozy") -> None:
        self.executable = executable

    def run_json(self, argv: Sequence[str], *, timeout_seconds: float) -> CommandResult:
        started = time.monotonic_ns()
        completed = subprocess.run(
            (self.executable, *argv), capture_output=True, text=True, check=False,
            timeout=max(1, timeout_seconds),
        )
        duration_ms = (time.monotonic_ns() - started) / 1_000_000
        if completed.returncode != 0:
            raise RuntimeError(f"Compozy command failed: {argv[0]}")
        try:
            value = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Compozy returned invalid JSON: {argv[0]}") from exc
        return CommandResult(value, duration_ms)


class CompozyV12RoleExecutor:
    """Execute all SDLC stages in one workspace-bound, idempotent Compozy session."""

    supports_idempotent_replay = True
    enforces_deadline = True

    def __init__(self, control_root: Path, transport: CompozyTransport | None = None) -> None:
        self.control_root = control_root.resolve()
        self.control_root.mkdir(parents=True, exist_ok=True)
        self.transport = transport or SubprocessCompozyTransport()
        self._sessions: dict[str, str] = {}
        self._cache: dict[str, NativeStepExecution] = {}
        self._provider_checked = False

    def execute(self, request: NativeStepRequest) -> NativeStepExecution:
        cached = self._cache.get(request.idempotency_key)
        if cached is not None:
            return cached
        remaining = self._remaining_seconds(request)
        if remaining <= 0:
            return self._outcome(request, "failed", 0, reason="controller-deadline-exceeded")
        self._verify_provider_configuration(remaining)
        session_id, setup_ms = self._session(request, remaining)
        prompt, sentinel = self._prompt(request)
        runtime_provider = self._runtime_provider(request.provider)
        argv = [
            "session", "prompt", session_id, prompt,
            "--provider", runtime_provider,
            "--reasoning-effort", "low",
            "--message-id", "msg_" + _sha(request.idempotency_key)[:24],
            "--idempotency-key", request.idempotency_key,
            "-o", "json",
        ]
        if runtime_provider == "codex":
            argv[argv.index("--reasoning-effort"):argv.index("--reasoning-effort")] = ["--model", request.model]
        try:
            prompt_started = time.monotonic_ns()
            try:
                turn = self.transport.run_json(argv, timeout_seconds=self._remaining_seconds(request))
                events = self._events(turn.value)
                prompt_ms = turn.duration_ms
            except RuntimeError:
                events = self._recover_events(session_id, request)
                prompt_ms = (time.monotonic_ns() - prompt_started) / 1_000_000
            text = self._agent_text(events)
            self._verify_turn(request, events, text, sentinel, runtime_provider)
            metadata = self._metadata(request, text, events, sentinel)
            tokens, cost = self._usage(events)
            metadata["usage_observation"] = self._usage_observation(events, tokens)
            cleanup_ms = self._stop(request, session_id) if request.step == "merge" else 0
            outcome = NativeStepExecution(
                status="completed", role=request.role, provider=request.provider, model=request.model,
                workspace=request.worktree, effective_work_ms=prompt_ms,
                external_wait_ms=0, orchestration_overhead_ms=setup_ms + cleanup_ms,
                tokens=tokens, cost_usd=cost,
                metadata=metadata, completion_proof=metadata.get("completion_proof"),
            )
        except (RuntimeError, subprocess.TimeoutExpired) as exc:
            outcome = self._outcome(
                request, "retry", setup_ms, reason=type(exc).__name__,
            )
        self._cache[request.idempotency_key] = outcome
        return outcome

    def close(self) -> None:
        """Best-effort deterministic cleanup for sessions left by terminal failures."""

        for run_id, session_id in tuple(self._sessions.items()):
            try:
                self.transport.run_json(
                    ("session", "stop", session_id, "-o", "json"), timeout_seconds=30,
                )
            finally:
                self._sessions.pop(run_id, None)

    def _verify_provider_configuration(self, timeout_seconds: float) -> None:
        if self._provider_checked:
            return
        result = self.transport.run_json(("config", "show", "-o", "json"), timeout_seconds=timeout_seconds)
        config = result.value.get("config", {}) if isinstance(result.value, Mapping) else {}
        providers = config.get("providers", {}) if isinstance(config, Mapping) else {}
        if not isinstance(providers, Mapping) or not isinstance(providers.get("codex"), Mapping):
            raise RuntimeError("Compozy Codex provider is unavailable")
        grok = providers.get("grok-cli")
        if not isinstance(grok, Mapping):
            raise RuntimeError("Compozy Grok provider is unavailable")
        validate_provider_config(grok)
        self._provider_checked = True

    def _session(self, request: NativeStepRequest, timeout_seconds: float) -> tuple[str, float]:
        existing = self._sessions.get(request.run_id)
        if existing:
            return existing, 0
        created = self.transport.run_json((
            "session", "new", "--cwd", str(request.worktree), "--agent", "general",
            "--network", "local", "--name", request.run_id, "-o", "json",
        ), timeout_seconds=timeout_seconds)
        if not isinstance(created.value, Mapping) or not isinstance(created.value.get("id"), str):
            raise RuntimeError("Compozy returned no session id")
        self._sessions[request.run_id] = created.value["id"]
        return created.value["id"], created.duration_ms

    def _stop(self, request: NativeStepRequest, session_id: str) -> float:
        result = self.transport.run_json(
            ("session", "stop", session_id, "-o", "json"),
            timeout_seconds=min(30, max(1, self._remaining_seconds(request))),
        )
        self._sessions.pop(request.run_id, None)
        return result.duration_ms

    def _recover_events(self, session_id: str, request: NativeStepRequest) -> list[Mapping[str, Any]]:
        """Recover bounded persisted events when Compozy's live SSE scanner overflows."""

        recovered: list[Mapping[str, Any]] = []
        for event_type in ("agent_message", "usage", "done"):
            result = self.transport.run_json((
                "session", "events", session_id, "--last", "500", "--type", event_type,
                "-o", "json",
            ), timeout_seconds=min(30, max(1, self._remaining_seconds(request))))
            recovered.extend(self._events(result.value))
        if not any(event.get("type") == "done" for event in recovered):
            raise RuntimeError("Compozy prompt stream failed before a persisted terminal event")
        return recovered

    @staticmethod
    def _runtime_provider(provider: str) -> str:
        return {"codex-cli": "codex", "codex": "codex", "grok-cli": "grok-cli"}[provider]

    @staticmethod
    def _remaining_seconds(request: NativeStepRequest) -> float:
        if request.deadline_epoch_ms is None:
            return 900
        return max(0, (request.deadline_epoch_ms - time.time() * 1000) / 1000)

    @staticmethod
    def _events(value: Any) -> list[Mapping[str, Any]]:
        if not isinstance(value, list) or any(not isinstance(event, Mapping) for event in value):
            raise RuntimeError("Compozy prompt returned an invalid event stream")
        return list(value)

    @staticmethod
    def _agent_text(events: Sequence[Mapping[str, Any]]) -> str:
        return "".join(
            str(event.get("text", event.get("content", {}).get("text", "")))
            for event in events if event.get("type") == "agent_message"
        )

    @staticmethod
    def _verify_turn(
        request: NativeStepRequest, events: Sequence[Mapping[str, Any]], text: str,
        sentinel: str, runtime_provider: str,
    ) -> None:
        providers: set[str] = set()
        models: set[str] = set()
        for event in events:
            runtime = event.get("prompt_runtime")
            if not isinstance(runtime, Mapping) and isinstance(event.get("content"), Mapping):
                runtime = event["content"].get("prompt_runtime")
            if isinstance(runtime, Mapping):
                if isinstance(runtime.get("provider"), str):
                    providers.add(str(runtime["provider"]))
                if isinstance(runtime.get("model"), str):
                    models.add(str(runtime["model"]))
        if sentinel not in text or not any(event.get("type") == "done" for event in events):
            raise RuntimeError("Compozy turn did not reach verified completion")
        if providers != {runtime_provider}:
            raise RuntimeError("Compozy effective provider mismatch")
        if runtime_provider == "codex" and models != {request.model}:
            raise RuntimeError("Compozy effective Codex model mismatch")

    @staticmethod
    def _prompt(request: NativeStepRequest) -> tuple[str, str]:
        sentinel = "V12_" + _sha(request.idempotency_key)[:20].upper()
        task = request.task_path.read_text(encoding="utf-8")
        handoff = request.handoff_path.read_text(encoding="utf-8") if request.handoff_path else ""
        factor = request.agentskit_context_path.read_text(encoding="utf-8") if request.agentskit_context_path else ""
        rules = (
            f"You are the frozen {request.role} for SDLC stage {request.step}. Work only in "
            f"{request.worktree}. Never change the benchmark control files. Complete this stage autonomously. "
            f"End with {sentinel}."
        )
        if request.step in {"requirements", "planning", "decomposition"}:
            rules += " Do not call tools or inspect files; all admissible inputs are supplied below."
        if request.step == "decomposition":
            rules += (
                " Include one JSON object with key handoff_payload containing exactly requirements, "
                "implementation_plan, and acceptance_criteria."
            )
        if request.step == "implementation":
            rules += " State both supplied SHA-256 digests verbatim before the sentinel."
        if request.step == "review":
            rules += (
                " Return a JSON object with completion_proof containing verified_gates and "
                "product_quality_score. The only allowed gates are: "
                + ", ".join(sorted(PRE_MERGE_QUALITY_GATES)) + "."
            )
        if request.step == "merge":
            rules += (
                " Return a JSON object with completion_proof containing verified_gates, "
                "product_quality_score, and the exact 40-character merge_commit. The only "
                "allowed gates are: " + ", ".join(sorted(REQUIRED_QUALITY_GATES)) + "."
            )
        return "\n\n".join((rules, "TASK:\n" + task, "HANDOFF:\n" + handoff, "AGENTSKIT:\n" + factor)), sentinel

    @classmethod
    def _metadata(
        cls, request: NativeStepRequest, text: str, events: Sequence[Mapping[str, Any]], sentinel: str,
    ) -> dict[str, Any]:
        metadata: dict[str, Any] = {
            "sentinel_sha256": _sha(sentinel),
            "event_count": len(events),
            "raw_output_persisted": False,
        }
        if request.step == "decomposition":
            payload = cls._extract_json(text, "handoff_payload").get("handoff_payload")
            metadata["handoff_payload"] = payload
        if request.step in {"review", "merge"}:
            proof = cls._extract_json(text, "completion_proof").get("completion_proof")
            if not isinstance(proof, Mapping):
                raise RuntimeError("Compozy stage output omitted completion proof")
            metadata["completion_proof"] = dict(proof)
        if request.handoff_path:
            digest = hashlib.sha256(request.handoff_path.read_bytes()).hexdigest()
            if digest not in text:
                raise RuntimeError("Grok did not acknowledge the handoff digest")
            metadata["handoff_sha256_observed"] = digest
        if request.agentskit_context_path:
            digest = hashlib.sha256(request.agentskit_context_path.read_bytes()).hexdigest()
            if digest not in text:
                raise RuntimeError("agent did not acknowledge the AgentsKit digest")
            metadata["agentskit_context_sha256_observed"] = digest
            metadata["agentskit_components_observed"] = ["doc-bridge", "playbook", "code-review"]
        return metadata

    @staticmethod
    def _extract_json(text: str, required_key: str) -> Mapping[str, Any]:
        decoder = json.JSONDecoder()
        for index, character in enumerate(text):
            if character != "{":
                continue
            try:
                value, _ = decoder.raw_decode(text[index:])
            except json.JSONDecodeError:
                continue
            if isinstance(value, Mapping) and required_key in value:
                return value
        raise RuntimeError("Compozy stage output omitted required JSON")

    @staticmethod
    def _usage(events: Sequence[Mapping[str, Any]]) -> tuple[dict[str, int], float]:
        tokens = {"input": 0, "output": 0, "cached": 0, "reasoning": 0}
        cost = 0.0
        for event in events:
            if event.get("type") != "usage":
                continue
            content = event.get("content", event)
            if not isinstance(content, Mapping):
                continue
            for target, aliases in {
                "input": ("input_tokens", "input"), "output": ("output_tokens", "output"),
                "cached": ("cached_tokens", "cached"), "reasoning": ("reasoning_tokens", "reasoning"),
            }.items():
                value = next((content.get(alias) for alias in aliases if isinstance(content.get(alias), int)), 0)
                tokens[target] += int(value)
            if isinstance(content.get("cost_usd"), (int, float)):
                cost += float(content["cost_usd"])
        return tokens, cost

    @staticmethod
    def _usage_observation(
        events: Sequence[Mapping[str, Any]], tokens: Mapping[str, int],
    ) -> dict[str, Any]:
        context_used = [
            event.get("usage", {}).get("context_used")
            for event in events
            if event.get("type") == "usage" and isinstance(event.get("usage"), Mapping)
            and isinstance(event["usage"].get("context_used"), int)
        ]
        return {
            "token_breakdown_observed": any(tokens.values()),
            "context_used": max(context_used) if context_used else None,
            "zero_tokens_mean_unavailable": not any(tokens.values()),
        }

    @staticmethod
    def _outcome(
        request: NativeStepRequest, status: str, external_wait_ms: float, *, reason: str,
    ) -> NativeStepExecution:
        return NativeStepExecution(
            status=status, role=request.role, provider=request.provider, model=request.model,
            workspace=request.worktree, effective_work_ms=0, external_wait_ms=max(0, external_wait_ms),
            orchestration_overhead_ms=0,
            tokens={"input": 0, "output": 0, "cached": 0, "reasoning": 0}, cost_usd=0,
            metadata={}, reason=reason,
        )
