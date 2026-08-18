"""Common stage routing and evidence validation for native v1.2 ADE sessions."""

from __future__ import annotations

from dataclasses import dataclass
import math
from pathlib import Path
from typing import Any, Mapping, Protocol

from .condition_runner import StepContext, StepResult


PLANNER_STEPS = {"requirements", "planning", "decomposition", "documentation", "merge"}
EXECUTOR_STEPS = {"implementation", "local-testing", "pull-request", "ci-qa"}
EVALUATOR_STEPS = {"review"}
ROLE_BINDINGS = {
    "planner_requirements_lead": ("codex-cli", "gpt-5.4"),
    "executor_fixer": ("grok-cli", "grok-4.5"),
    "independent_evaluator": ("codex", "gpt-5.4-mini"),
}


@dataclass(frozen=True)
class NativeStepRequest:
    run_id: str
    condition_id: str
    task_id: str
    step: str
    role: str
    provider: str
    model: str
    worktree: Path
    branch: str
    idempotency_key: str
    deadline_epoch_ms: float | None
    task_path: Path
    handoff_path: Path | None
    agentskit_context_path: Path | None


@dataclass(frozen=True)
class NativeStepExecution:
    status: str
    role: str
    provider: str
    model: str
    workspace: Path
    effective_work_ms: float
    external_wait_ms: float
    orchestration_overhead_ms: float
    token_cost_accounting_observed: bool
    tokens: Mapping[str, int]
    cost_usd: float
    metadata: Mapping[str, Any]
    artifacts: tuple[dict[str, str], ...] = ()
    completion_proof: Mapping[str, Any] | None = None
    reason: str | None = None


class V12RoleExecutor(Protocol):
    supports_idempotent_replay: bool
    enforces_deadline: bool

    def execute(self, request: NativeStepRequest) -> NativeStepExecution: ...


class V12NativeStageBackend:
    """Route SDLC stages to fixed roles and emit complete measured accounting."""

    supports_idempotent_replay = True
    enforces_deadline = True

    def __init__(self, executor: V12RoleExecutor) -> None:
        if getattr(executor, "supports_idempotent_replay", False) is not True:
            raise ValueError("native role executor must support idempotent replay")
        if getattr(executor, "enforces_deadline", False) is not True:
            raise ValueError("native role executor must enforce deadlines")
        self.executor = executor

    def execute_step(self, context: StepContext) -> StepResult:
        role = self._role_for_step(context.step.name)
        provider, model = ROLE_BINDINGS[role]
        task_path = context.worktree / "tasks/public" / f"{context.assignment.task_id}.md"
        if not task_path.is_file():
            return StepResult("invalid-measurement", reason="frozen-task-missing-from-worktree")
        request = NativeStepRequest(
            run_id=context.assignment.run_id,
            condition_id=context.assignment.condition_id,
            task_id=context.assignment.task_id,
            step=context.step.name,
            role=role,
            provider=provider,
            model=model,
            worktree=context.worktree.resolve(),
            branch=context.branch,
            idempotency_key=context.idempotency_key,
            deadline_epoch_ms=context.deadline_epoch_ms,
            task_path=task_path,
            handoff_path=context.handoff_path,
            agentskit_context_path=context.agentskit_context_path,
        )
        execution = self.executor.execute(request)
        validation_error = self._validate_execution(request, execution)
        self._record_accounting(context, execution, valid=validation_error is None)
        if validation_error:
            return StepResult("invalid-measurement", reason=validation_error)
        if execution.status == "retry":
            return StepResult.retry(execution.reason or "native-transport-retry")
        if execution.status == "failed":
            return StepResult.failed(execution.reason or "native-step-failed")
        if execution.status == "human-required":
            return StepResult.human_required(execution.reason or "native-hitl-trigger")
        if execution.status == "timeout":
            return StepResult("timeout", reason=execution.reason or "controller-deadline-exceeded")
        return StepResult.completed(
            artifacts=execution.artifacts,
            metadata=execution.metadata,
            completion_proof=execution.completion_proof,
        )

    def close(self) -> None:
        close = getattr(self.executor, "close", None)
        if callable(close):
            close()

    @staticmethod
    def _role_for_step(step: str) -> str:
        if step in PLANNER_STEPS:
            return "planner_requirements_lead"
        if step in EXECUTOR_STEPS:
            return "executor_fixer"
        if step in EVALUATOR_STEPS:
            return "independent_evaluator"
        raise ValueError(f"unsupported v1.2 SDLC step: {step}")

    @staticmethod
    def _validate_execution(request: NativeStepRequest, execution: NativeStepExecution) -> str | None:
        if execution.status not in {"completed", "retry", "failed", "human-required", "timeout"}:
            return "native-step-status-invalid"
        if (
            execution.role != request.role
            or execution.provider != request.provider
            or execution.model != request.model
        ):
            return "native-role-binding-mismatch"
        if execution.workspace.resolve() != request.worktree:
            return "native-workspace-boundary-mismatch"
        if not isinstance(execution.token_cost_accounting_observed, bool):
            return "native-accounting-observation-invalid"
        if not all(math.isfinite(value) for value in (
            execution.effective_work_ms, execution.external_wait_ms,
            execution.orchestration_overhead_ms, execution.cost_usd,
        )):
            return "native-accounting-non-finite"
        if (
            execution.effective_work_ms < 0 or execution.external_wait_ms < 0
            or execution.orchestration_overhead_ms < 0 or execution.cost_usd < 0
        ):
            return "native-accounting-negative"
        if set(execution.tokens) != {"input", "output", "cached", "reasoning"}:
            return "native-token-accounting-incomplete"
        if any(not isinstance(value, int) or value < 0 for value in execution.tokens.values()):
            return "native-token-accounting-invalid"
        if execution.status == "completed" and execution.reason is not None:
            return "completed-native-step-has-failure-reason"
        return None

    @staticmethod
    def _record_accounting(
        context: StepContext, execution: NativeStepExecution, *, valid: bool,
    ) -> None:
        tokens = dict(execution.tokens) if set(execution.tokens) == {"input", "output", "cached", "reasoning"} else {
            "input": 0, "output": 0, "cached": 0, "reasoning": 0,
        }
        context.bundle.ledger.record(
            stage_id=context.step.stage_id,
            actor=context.step.actor,
            event_type="backend.attempt.effective-work",
            time_category="effective_work",
            duration_ms=max(0, execution.effective_work_ms) if math.isfinite(execution.effective_work_ms) else 0,
            status="completed" if valid else "failed",
            payload={
                "role": execution.role, "provider": execution.provider,
                "model": execution.model, "idempotency_key": context.idempotency_key,
                "token_cost_accounting_observed": execution.token_cost_accounting_observed,
            },
            tool=context.accounting_tool,
            tokens=tokens,
            cost_usd=max(0, execution.cost_usd) if math.isfinite(execution.cost_usd) else 0,
        )
        context.bundle.ledger.record(
            stage_id=context.step.stage_id,
            actor="infrastructure",
            event_type="backend.attempt.external-wait",
            time_category="external_wait",
            duration_ms=max(0, execution.external_wait_ms) if math.isfinite(execution.external_wait_ms) else 0,
            status="completed" if valid else "failed",
            payload={"idempotency_key": context.idempotency_key},
            tool=context.accounting_tool,
        )
        context.bundle.ledger.record(
            stage_id=context.step.stage_id,
            actor="infrastructure",
            event_type="backend.attempt.orchestration-overhead",
            time_category="orchestration_overhead",
            duration_ms=(
                max(0, execution.orchestration_overhead_ms)
                if math.isfinite(execution.orchestration_overhead_ms) else 0
            ),
            status="completed" if valid else "failed",
            payload={"idempotency_key": context.idempotency_key},
            tool=context.accounting_tool,
        )
