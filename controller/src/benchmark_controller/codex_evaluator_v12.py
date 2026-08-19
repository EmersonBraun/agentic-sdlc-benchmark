"""Neutral read-only Codex CLI evaluator for the frozen v1.2 topology."""

from __future__ import annotations

import hashlib
import json
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Protocol, Sequence

from .condition_runner import PRE_MERGE_QUALITY_GATES, REQUIRED_QUALITY_GATES, StepContext
from .v12_native_backend import NativeStepExecution, NativeStepRequest

RUBRIC_WEIGHTS = {
    "functional_correctness": 40,
    "security_authorization": 15,
    "regressions": 15,
    "tests": 10,
    "architecture_maintainability": 10,
    "documentation_operations": 5,
    "scope_discipline": 5,
}
EXTERNAL_ONLY_GATES = {"essential-hidden-tests", "ledger"}


@dataclass(frozen=True)
class CodexCommandResult:
    stdout: str
    duration_ms: float


class CodexTransport(Protocol):
    def run(self, argv: Sequence[str], *, timeout_seconds: float) -> CodexCommandResult: ...


class SubprocessCodexTransport:
    def run(self, argv: Sequence[str], *, timeout_seconds: float) -> CodexCommandResult:
        started = time.monotonic_ns()
        completed = subprocess.run(
            tuple(argv), capture_output=True, text=True, check=False, timeout=timeout_seconds,
        )
        duration_ms = (time.monotonic_ns() - started) / 1_000_000
        if completed.returncode != 0:
            raise RuntimeError("Codex evaluator command failed")
        return CodexCommandResult(completed.stdout, duration_ms)


class CodexEvaluatorV12RoleExecutor:
    """Evaluate product evidence without joining any measured ADE session."""

    supports_idempotent_replay = True
    enforces_deadline = True

    def __init__(self, transport: CodexTransport | None = None) -> None:
        self.transport = transport or SubprocessCodexTransport()
        self._cache: dict[str, NativeStepExecution] = {}

    def execute(self, request: NativeStepRequest) -> NativeStepExecution:
        if (request.role, request.provider, request.model) != (
            "independent_evaluator", "codex", "gpt-5.4-mini",
        ):
            return self._outcome(request, "failed", "evaluator-role-binding-mismatch")
        key = request.idempotency_key
        if key in self._cache:
            return self._cache[key]
        remaining = self._remaining(request)
        if remaining <= 0:
            return self._outcome(request, "timeout", "controller-deadline-exceeded")
        prompt = self._prompt(request)
        argv = (
            "codex", "exec", "-m", "gpt-5.4-mini", "-s", "read-only",
            "--ephemeral", "--ignore-user-config",
            "--disable", "plugins", "--disable", "remote_plugin",
            "--disable", "skill_search", "--disable", "apps",
            "--disable", "multi_agent", "--json", "-C",
            str(request.worktree), prompt,
        )
        started = time.monotonic_ns()
        try:
            result = self.transport.run(argv, timeout_seconds=remaining)
            events = self._events(result.stdout)
            proof = self._proof(events)
            tokens, usage_observed = self._usage(events)
            execution = NativeStepExecution(
                status="completed", role=request.role, provider=request.provider,
                model=request.model, workspace=request.worktree,
                effective_work_ms=result.duration_ms, external_wait_ms=0,
                orchestration_overhead_ms=0,
                token_cost_accounting_observed=False, tokens=tokens, cost_usd=0,
                metadata={
                    "command_sha256": hashlib.sha256(
                        json.dumps(argv[:-1], separators=(",", ":")).encode()
                    ).hexdigest(),
                    "raw_output_persisted": False,
                    "sandbox": "read-only",
                    "ephemeral": True,
                    "disabled_capabilities": [
                        "apps", "multi_agent", "plugins", "remote_plugin", "skill_search",
                    ],
                    "external_only_gates": sorted(EXTERNAL_ONLY_GATES),
                    "usage_observation": {
                        "token_breakdown_observed": usage_observed,
                        "cost_observed": False,
                        "zero_cost_means_unavailable": True,
                    },
                },
                completion_proof=proof,
            )
        except subprocess.TimeoutExpired:
            return self._outcome(
                request, "timeout", "controller-deadline-exceeded",
                effective_work_ms=(time.monotonic_ns() - started) / 1_000_000,
            )
        except (RuntimeError, TypeError, ValueError, json.JSONDecodeError):
            return self._outcome(
                request, "failed", "invalid-evaluator-output",
                effective_work_ms=(time.monotonic_ns() - started) / 1_000_000,
            )
        self._cache[key] = execution
        return execution

    @staticmethod
    def _events(output: str) -> list[Mapping[str, Any]]:
        events: list[Mapping[str, Any]] = []
        for line in output.splitlines():
            if not line.strip().startswith("{"):
                continue
            value = json.loads(line)
            if isinstance(value, Mapping):
                events.append(value)
        if not events:
            raise RuntimeError("Codex evaluator emitted no JSONL events")
        return events

    @staticmethod
    def _proof(events: list[Mapping[str, Any]]) -> dict[str, Any]:
        completed = [event for event in events if event.get("type") == "turn.completed"]
        failed = [event for event in events if event.get("type") in {"turn.failed", "error"}]
        if len(completed) != 1 or failed:
            raise RuntimeError("Codex evaluator turn did not complete cleanly")
        messages = [
            item.get("text")
            for event in events if event.get("type") == "item.completed"
            for item in [event.get("item", {})]
            if isinstance(item, Mapping) and item.get("type") == "agent_message"
        ]
        proofs: list[Mapping[str, Any]] = []
        for message in messages:
            if not isinstance(message, str):
                continue
            candidate = message.strip()
            if candidate.startswith("```") and candidate.endswith("```"):
                candidate = candidate.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
            try:
                value = json.loads(candidate)
            except json.JSONDecodeError:
                continue
            proof = value.get("completion_proof") if isinstance(value, Mapping) else None
            if isinstance(proof, Mapping):
                proofs.append(proof)
        if len(proofs) != 1:
            raise RuntimeError("Codex evaluator final proof is missing or ambiguous")
        normalized = dict(proofs[0])
        scores = normalized.get("scores")
        if not isinstance(scores, Mapping) or set(scores) != set(RUBRIC_WEIGHTS):
            raise RuntimeError("Codex evaluator omitted frozen rubric scores")
        if any(
            not isinstance(value, (int, float)) or isinstance(value, bool) or not 0 <= value <= 100
            for value in scores.values()
        ):
            raise RuntimeError("Codex evaluator rubric score is invalid")
        normalized["product_quality_score"] = round(sum(
            float(scores[name]) * weight / 100 for name, weight in RUBRIC_WEIGHTS.items()
        ), 3)
        gates = normalized.get("verified_gates")
        if not isinstance(gates, list) or EXTERNAL_ONLY_GATES.intersection(gates):
            raise RuntimeError("Codex evaluator claimed externally verified gates")
        return normalized

    @staticmethod
    def _usage(events: list[Mapping[str, Any]]) -> tuple[dict[str, int], bool]:
        completed = [event for event in events if event.get("type") == "turn.completed"]
        usage = completed[-1].get("usage", {}) if completed else {}
        if not isinstance(usage, Mapping):
            usage = {}
        source_keys = {
            "input": "input_tokens", "output": "output_tokens",
            "cached": "cached_input_tokens", "reasoning": "reasoning_output_tokens",
        }
        observed = bool(completed) and all(
            isinstance(usage.get(source), int)
            and not isinstance(usage.get(source), bool)
            and usage[source] >= 0
            for source in source_keys.values()
        )
        tokens = {
            target: int(usage[source]) if observed else 0
            for target, source in source_keys.items()
        }
        return tokens, observed

    @staticmethod
    def _prompt(request: NativeStepRequest) -> str:
        gates = PRE_MERGE_QUALITY_GATES if request.step == "review" else REQUIRED_QUALITY_GATES
        inspectable = set(gates) - EXTERNAL_ONLY_GATES
        return (
            "Act as the independent evaluator for a controlled SDLC benchmark. "
            "Inspect the current repository read-only. Run only non-mutating checks. "
            "Return exactly one compact JSON object with key completion_proof containing "
            "verified_gates (an array), scores (an object with every frozen rubric dimension), "
            "and, for merge only, "
            "merge_commit equal to git HEAD. Include a gate only when supported by repository "
            "evidence. Never claim ledger or essential-hidden-tests; those require controller-owned "
            "evidence outside this worktree. Inspectable gates are: "
            + ", ".join(sorted(inspectable)) + ". Frozen rubric weights are: "
            + json.dumps(RUBRIC_WEIGHTS, sort_keys=True) + ". Score every dimension from 0 to 100."
        )

    @staticmethod
    def _remaining(request: NativeStepRequest) -> float:
        if request.deadline_epoch_ms is None:
            return 900
        return max(0, (request.deadline_epoch_ms - time.time() * 1000) / 1000)

    @staticmethod
    def _outcome(
        request: NativeStepRequest, status: str, reason: str, *, effective_work_ms: float = 0,
    ) -> NativeStepExecution:
        return NativeStepExecution(
            status=status, role=request.role, provider=request.provider, model=request.model,
            workspace=request.worktree, effective_work_ms=max(0, effective_work_ms), external_wait_ms=0,
            orchestration_overhead_ms=0, token_cost_accounting_observed=False,
            tokens={"input": 0, "output": 0, "cached": 0, "reasoning": 0},
            cost_usd=0, metadata={}, reason=reason,
        )


class CodexV12CompletionVerifier:
    """Bind runner verification to the same frozen neutral evaluator contract."""

    provider = "codex"
    model = "gpt-5.4-mini"
    enforces_deadline = True

    def __init__(self, executor: CodexEvaluatorV12RoleExecutor) -> None:
        self.executor = executor

    def verify(self, context: StepContext, proof: Mapping[str, Any]) -> bool:
        step = "review" if context.idempotency_key.endswith("pre-merge-verification") else "merge"
        request = NativeStepRequest(
            run_id=context.assignment.run_id,
            condition_id=context.assignment.condition_id,
            task_id=context.assignment.task_id,
            step=step,
            role="independent_evaluator",
            provider=self.provider,
            model=self.model,
            worktree=context.worktree.resolve(),
            branch=context.branch,
            idempotency_key=context.idempotency_key,
            deadline_epoch_ms=context.deadline_epoch_ms,
            task_path=context.worktree / "tasks/public" / f"{context.assignment.task_id}.md",
            handoff_path=context.handoff_path,
            agentskit_context_path=context.agentskit_context_path,
        )
        execution = self.executor.execute(request)
        self._record(context, execution, step)
        evaluated = execution.completion_proof or {}
        required = PRE_MERGE_QUALITY_GATES if step == "review" else REQUIRED_QUALITY_GATES
        return all((
            execution.status == "completed",
            set(evaluated.get("verified_gates", [])) == required,
            set(proof.get("verified_gates", [])) == required,
            isinstance(evaluated.get("product_quality_score"), (int, float)),
            evaluated.get("product_quality_score", 0) >= 80,
            isinstance(proof.get("product_quality_score"), (int, float)),
            proof.get("product_quality_score", 0) >= 80,
            step != "merge" or evaluated.get("merge_commit") == proof.get("merge_commit"),
        ))

    @staticmethod
    def _record(context: StepContext, execution: NativeStepExecution, step: str) -> None:
        stage_id = "review" if step == "review" else "merge"
        common = dict(
            stage_id=stage_id,
            status="completed" if execution.status == "completed" else "failed",
            tool=context.accounting_tool,
        )
        context.bundle.ledger.record(
            actor="evaluator", event_type="backend.attempt.effective-work",
            time_category="effective_work", duration_ms=execution.effective_work_ms,
            payload={
                "role": execution.role, "provider": execution.provider,
                "model": execution.model,
                "token_cost_accounting_observed": execution.token_cost_accounting_observed,
            },
            tokens=dict(execution.tokens), cost_usd=execution.cost_usd,
            token_cost_accounting_observed=execution.token_cost_accounting_observed,
            **common,
        )
        context.bundle.ledger.record(
            actor="infrastructure", event_type="backend.attempt.external-wait",
            time_category="external_wait", duration_ms=execution.external_wait_ms,
            payload={"verification": step}, **common,
        )
        context.bundle.ledger.record(
            actor="infrastructure", event_type="backend.attempt.orchestration-overhead",
            time_category="orchestration_overhead",
            duration_ms=execution.orchestration_overhead_ms,
            payload={"verification": step}, **common,
        )
