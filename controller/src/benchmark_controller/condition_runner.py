"""Persistent composed ADE x harness x AgentsKit condition execution."""

from __future__ import annotations

import json
import hashlib
import subprocess
import tempfile
import time
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Protocol

from .collection import ExecutionOutcome
from .matrix import MatrixAssignment
from .run_bundles import PreparedRunBundle


@dataclass(frozen=True)
class ConditionStep:
    name: str
    stage_id: str
    actor: str


CONDITION_STEPS = (
    ConditionStep("requirements", "requirements", "planner"),
    ConditionStep("planning", "planning", "planner"),
    ConditionStep("decomposition", "decomposition", "planner"),
    ConditionStep("implementation", "implementation", "executor"),
    ConditionStep("local-testing", "local-testing", "executor"),
    ConditionStep("pull-request", "pull-request", "executor"),
    ConditionStep("ci-qa", "ci-qa", "reviewer-qa"),
    ConditionStep("review", "review", "reviewer-functional"),
    ConditionStep("documentation", "documentation", "controller"),
    ConditionStep("merge", "merge", "controller"),
)
REQUIRED_QUALITY_GATES = frozenset({
    "build", "typecheck", "ci", "mandatory-requirements",
    "essential-hidden-tests", "migrations", "security", "review",
    "documentation", "merge", "ledger", "product-quality-score",
})
PRE_MERGE_QUALITY_GATES = REQUIRED_QUALITY_GATES - {"merge"}
REQUIRED_BUDGET_KEYS = frozenset({
    "wall_time_ms", "effective_work_ms", "external_wait_ms", "tokens",
    "cost_usd", "stage_effective_work_ms",
})


@dataclass(frozen=True)
class WorktreeLease:
    path: Path
    branch: str
    base_commit: str


class WorktreeProvider(Protocol):
    def acquire(self, *, run_id: str, base_commit: str) -> WorktreeLease: ...

    def release(self, lease: WorktreeLease) -> None:
        """Idempotently release a lease, including after a cleanup crash."""
        ...


class GitWorktreeProvider:
    """Create one controller-owned isolation boundary per benchmark run."""

    def __init__(self, repository: Path, worktree_root: Path) -> None:
        self.repository = repository.resolve()
        self.worktree_root = worktree_root.resolve()

    def acquire(self, *, run_id: str, base_commit: str) -> WorktreeLease:
        branch = f"benchmark/{run_id}"
        path = (self.worktree_root / run_id).resolve()
        if self.worktree_root not in path.parents:
            raise ValueError("worktree path escapes the configured root")
        self.worktree_root.mkdir(parents=True, exist_ok=True)
        if path.is_dir():
            self._verify_worktree(path=path, branch=branch, base_commit=base_commit)
            return WorktreeLease(path=path, branch=branch, base_commit=base_commit)
        completed = subprocess.run(
            ["git", "worktree", "add", "-b", branch, str(path), base_commit],
            cwd=self.repository,
            check=False,
            capture_output=True,
            text=True,
        )
        if completed.returncode != 0:
            raise RuntimeError("git worktree creation failed")
        try:
            self._verify_worktree(path=path, branch=branch, base_commit=base_commit)
        except Exception:
            removed = subprocess.run(
                ["git", "worktree", "remove", "--force", str(path)],
                cwd=self.repository, check=False, capture_output=True, text=True,
            )
            deleted = subprocess.run(
                ["git", "branch", "-D", branch],
                cwd=self.repository, check=False, capture_output=True, text=True,
            )
            if removed.returncode != 0 or deleted.returncode != 0:
                raise RuntimeError("worktree verification and rollback failed")
            raise
        return WorktreeLease(path=path, branch=branch, base_commit=base_commit)

    def release(self, lease: WorktreeLease) -> None:
        path = lease.path.resolve()
        if self.worktree_root not in path.parents:
            raise ValueError("worktree cleanup path escapes the configured root")
        if not path.exists():
            listed = self._git(("worktree", "list", "--porcelain"))
            if f"worktree {path}" not in listed.splitlines():
                return
            raise RuntimeError("missing worktree remains registered")
        completed = subprocess.run(
            ["git", "worktree", "remove", str(path)],
            cwd=self.repository,
            check=False,
            capture_output=True,
            text=True,
        )
        if completed.returncode != 0:
            raise RuntimeError("git worktree cleanup failed")

    def _git(self, args: tuple[str, ...]) -> str:
        completed = subprocess.run(
            ("git", *args), cwd=self.repository, check=False, capture_output=True, text=True
        )
        if completed.returncode != 0:
            raise RuntimeError("existing worktree could not be inspected")
        return completed.stdout.strip()

    def _verify_worktree(self, *, path: Path, branch: str, base_commit: str) -> None:
        observed_commit = self._git(("-C", str(path), "rev-parse", "HEAD"))
        observed_branch = self._git(("-C", str(path), "branch", "--show-current"))
        status = self._git(("-C", str(path), "status", "--porcelain", "--untracked-files=all"))
        if observed_commit != base_commit or observed_branch != branch or status:
            raise RuntimeError("worktree identity or cleanliness does not match the run")


@dataclass(frozen=True)
class StepContext:
    assignment: MatrixAssignment
    bundle: PreparedRunBundle
    step: ConditionStep
    attempt: int
    worktree: Path
    branch: str
    idempotency_key: str
    deadline_epoch_ms: float | None
    accounting_tool: str
    worktree_mode: str = "controller-isolated-native-delegation"
    handoff_path: Path | None = None
    agentskit_context_path: Path | None = None


@dataclass(frozen=True)
class StepResult:
    status: str
    reason: str | None = None
    artifacts: tuple[dict[str, str], ...] = ()
    metadata: Mapping[str, Any] | None = None
    completion_proof: Mapping[str, Any] | None = None

    def __post_init__(self) -> None:
        if self.status not in {
            "completed", "retry", "failed", "human-required", "timeout",
            "budget-exceeded", "invalid-measurement",
        }:
            raise ValueError(f"invalid step status: {self.status!r}")

    @classmethod
    def completed(
        cls,
        *,
        artifacts: tuple[dict[str, str], ...] = (),
        metadata: Mapping[str, Any] | None = None,
        completion_proof: Mapping[str, Any] | None = None,
    ) -> "StepResult":
        return cls(
            "completed", artifacts=artifacts, metadata=metadata,
            completion_proof=completion_proof,
        )

    @classmethod
    def retry(cls, reason: str) -> "StepResult":
        return cls("retry", reason=reason)

    @classmethod
    def failed(cls, reason: str) -> "StepResult":
        return cls("failed", reason=reason)

    @classmethod
    def human_required(cls, reason: str) -> "StepResult":
        return cls("human-required", reason=reason)


class ConditionStepBackend(Protocol):
    """ADE-specific workflow implementation behind a common state contract."""

    supports_idempotent_replay: bool
    enforces_deadline: bool

    def execute_step(self, context: StepContext) -> StepResult: ...


class CompletionVerifier(Protocol):
    """Independently validate the backend's quality-gate evidence."""

    enforces_deadline: bool

    def verify(
        self, context: StepContext, proof: Mapping[str, Any]
    ) -> bool | "VerificationDecision": ...


@dataclass(frozen=True)
class VerificationDecision:
    accepted: bool
    canonical_proof: Mapping[str, Any] | None = None


class RetryableConditionError(RuntimeError):
    """Explicit transport failure eligible for bounded retry."""


class ComposedConditionRunner:
    """Run continuously until a measured terminal state; never resume partial runs."""

    state_filename = "condition-runner-state.json"
    state_schema_version = "condition-runner-state-v1.1"
    runner_tool = "condition-runner-v1.1"
    accepts_v12 = False

    def __init__(
        self,
        backend: ConditionStepBackend,
        worktrees: WorktreeProvider,
        verifier: CompletionVerifier,
        *,
        max_attempts: int = 3,
        retry_backoff_seconds: float = 1.0,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        if max_attempts < 1:
            raise ValueError("max_attempts must be positive")
        if retry_backoff_seconds <= 0:
            raise ValueError("retry_backoff_seconds must be positive")
        if getattr(backend, "supports_idempotent_replay", False) is not True:
            raise ValueError("condition backend must guarantee idempotent replay")
        if getattr(backend, "enforces_deadline", False) is not True:
            raise ValueError("condition backend must enforce the controller deadline")
        if getattr(verifier, "enforces_deadline", False) is not True:
            raise ValueError("completion verifier must enforce the controller deadline")
        self.backend = backend
        self.worktrees = worktrees
        self.verifier = verifier
        self.max_attempts = max_attempts
        self.retry_backoff_seconds = retry_backoff_seconds
        self.sleeper = sleeper

    def execute(self, assignment: MatrixAssignment, bundle: PreparedRunBundle) -> ExecutionOutcome:
        if bundle.manifest.get("protocol_version") == "v1.2" and not self.accepts_v12:
            raise RuntimeError("v1.2 requires its native ADE runner; the v1.1 harness runner is prohibited")
        self._validate_manifest_identity(assignment, bundle)
        state_path = bundle.directory / self.state_filename
        state_existed = state_path.exists()
        state = self._load_or_create_state(state_path, assignment, bundle)
        if state.get("terminal_state"):
            if state.get("cleanup_pending"):
                lease = self._lease(state, require_path=False)
                if lease is None:
                    raise RuntimeError("terminal cleanup has no worktree lease")
                self._complete_cleanup(lease, bundle, state_path, state)
            return ExecutionOutcome(
                str(state["terminal_state"]),
                tuple(state.get("artifacts", [])),
                state.get("failure"),
            )
        if state_existed:
            failure = {"reason": "partial-runs-are-never-resumed"}
            state["terminal_state"] = "INVALID_MEASUREMENT"
            state["failure"] = failure
            self._write_state(state_path, state)
            return ExecutionOutcome("INVALID_MEASUREMENT", tuple(state.get("artifacts", [])), failure)
        initial_limit = self._limit_outcome(bundle, state)
        if initial_limit is not None:
            state["terminal_state"] = initial_limit.terminal_state
            state["failure"] = initial_limit.failure
            self._write_state(state_path, state)
            return initial_limit
        lease = self._lease(state)
        if lease is None:
            lease = self.worktrees.acquire(
                run_id=assignment.run_id,
                base_commit=str(bundle.manifest["base_commit"]),
            )
            state["worktree"] = {
                "path": str(lease.path),
                "branch": lease.branch,
                "base_commit": lease.base_commit,
            }
            self._write_state(state_path, state)
        if not state.get("worktree_event_recorded"):
            bundle.ledger.record(
                stage_id="intake",
                actor="controller",
                event_type="condition.worktree.acquired",
                time_category="orchestration_overhead",
                duration_ms=0,
                status="completed",
                payload={"branch": lease.branch, "mode": "controller-isolated-native-delegation"},
                tool=self.runner_tool,
            )
            state["worktree_event_recorded"] = True
            self._write_state(state_path, state)

        artifacts = list(state.get("artifacts", []))
        completed = list(state["completed_steps"])
        for step in CONDITION_STEPS:
            if step.name in completed:
                continue
            if step.name == "merge":
                proof = state.get("completion_proof")
                context = StepContext(
                    assignment, bundle, step, 0, lease.path, lease.branch,
                    f"{assignment.run_id}:pre-merge-verification",
                    self._deadline_epoch_ms(bundle, state),
                    f"condition-accounting:{assignment.run_id}:pre-merge-verification",
                )
                if (
                    not isinstance(proof, Mapping)
                    or not self._valid_pre_merge_proof(proof)
                    or not self._verify(context, proof, phase="pre-merge")
                ):
                    failure = {"reason": "independent-pre-merge-verification-failed"}
                    state["terminal_state"] = "FAILED"
                    state["failure"] = failure
                    self._write_state(state_path, state)
                    return ExecutionOutcome("FAILED", tuple(artifacts), failure)
                limit = self._limit_outcome(bundle, state)
                if limit is not None:
                    state["terminal_state"] = limit.terminal_state
                    state["failure"] = limit.failure
                    self._write_state(state_path, state)
                    return limit
            outcome = self._run_step(step, assignment, bundle, lease, state_path, state)
            if outcome is not None:
                state["terminal_state"] = outcome.terminal_state
                state["failure"] = outcome.failure
                state["current_step"] = None
                self._write_state(state_path, state)
                return outcome
            completed.append(step.name)
            state["completed_steps"] = completed
            state["current_step"] = None
            artifacts = list(state.get("artifacts", artifacts))
            self._write_state(state_path, state)

        proof = state.get("completion_proof")
        try:
            self._validate_artifacts(bundle, tuple(state.get("artifacts", [])))
        except (OSError, ValueError) as exc:
            failure = {"reason": "final-artifact-revalidation-failed", "error_type": type(exc).__name__}
            state["terminal_state"] = "INVALID_MEASUREMENT"
            state["failure"] = failure
            self._write_state(state_path, state)
            return ExecutionOutcome("INVALID_MEASUREMENT", tuple(artifacts), failure)
        verification_context = StepContext(
            assignment=assignment,
            bundle=bundle,
            step=CONDITION_STEPS[-1],
            attempt=int(state["attempts"].get("merge", 1)),
            worktree=lease.path,
            branch=lease.branch,
            idempotency_key=f"{assignment.run_id}:completion-verification",
            deadline_epoch_ms=self._deadline_epoch_ms(bundle, state),
            accounting_tool=f"condition-accounting:{assignment.run_id}:completion-verification",
        )
        if (
            not isinstance(proof, Mapping)
            or not self._valid_completion_proof(proof)
            or not self._verify(verification_context, proof, phase="final")
        ):
            failure = {"reason": "independent-quality-gate-verification-failed"}
            state["terminal_state"] = "FAILED"
            state["failure"] = failure
            self._write_state(state_path, state)
            return ExecutionOutcome("FAILED", tuple(artifacts), failure)

        state["terminal_state"] = "MERGED"
        state["cleanup_pending"] = True
        self._write_state(state_path, state)
        try:
            self._complete_cleanup(lease, bundle, state_path, state)
        except Exception as exc:
            state["terminal_state"] = "INFRASTRUCTURE_FAILURE"
            state["cleanup_pending"] = True
            state["cleanup_error"] = type(exc).__name__
            state["failure"] = {"step": "cleanup", "error_type": type(exc).__name__}
            self._write_state(state_path, state)
            return ExecutionOutcome("INFRASTRUCTURE_FAILURE", tuple(artifacts), state["failure"])
        return ExecutionOutcome("MERGED", tuple(artifacts))

    def _verify(self, context: StepContext, proof: Mapping[str, Any], *, phase: str) -> bool:
        ledger_lines_before = self._ledger_line_count(context.bundle)
        result = self.verifier.verify(context, proof)
        decision = result.accepted if isinstance(result, VerificationDecision) else bool(result)
        accounting_valid = self._has_backend_timing_evidence(
            context.bundle,
            ledger_lines_before,
            step=ConditionStep(phase, "review" if phase == "pre-merge" else "merge", "evaluator"),
            accounting_tool=context.accounting_tool,
        )
        decision = decision and accounting_valid
        canonical = result.canonical_proof if isinstance(result, VerificationDecision) else None
        if decision and canonical is not None:
            if not isinstance(proof, dict):
                decision = False
            else:
                proof.clear()
                proof.update(canonical)
        context.bundle.ledger.record(
            stage_id="review" if phase == "pre-merge" else "merge",
            actor="evaluator",
            event_type=f"condition.verification.{phase}",
            time_category="instrumentation_overhead",
            duration_ms=0,
            status="completed" if decision else "failed",
            payload={
                "phase": phase,
                "proof_sha256": hashlib.sha256(
                    json.dumps(dict(proof), sort_keys=True, separators=(",", ":")).encode()
                ).hexdigest(),
                "verifier": type(self.verifier).__name__,
                "canonical_proof_published": decision and canonical is not None,
            },
            tool=self.runner_tool,
        )
        return decision

    def _complete_cleanup(
        self,
        lease: WorktreeLease,
        bundle: PreparedRunBundle,
        state_path: Path,
        state: dict[str, Any],
    ) -> None:
        self.worktrees.release(lease)
        if not state.get("worktree_release_event_recorded"):
            bundle.ledger.record(
                stage_id="documentation",
                actor="controller",
                event_type="condition.worktree.released",
                time_category="orchestration_overhead",
                duration_ms=0,
                status="completed",
                payload={"branch": lease.branch},
                tool=self.runner_tool,
            )
        state["worktree_release_event_recorded"] = True
        state["worktree_released"] = True
        state["cleanup_pending"] = False
        self._write_state(state_path, state)

    def _run_step(
        self,
        step: ConditionStep,
        assignment: MatrixAssignment,
        bundle: PreparedRunBundle,
        lease: WorktreeLease,
        state_path: Path,
        state: dict[str, Any],
    ) -> ExecutionOutcome | None:
        prior_attempts = int(state["attempts"].get(step.name, 0))
        first_attempt = prior_attempts if state.get("current_step") == step.name else prior_attempts + 1
        first_attempt = max(1, first_attempt)
        for attempt in range(first_attempt, self.max_attempts + 1):
            state["current_step"] = step.name
            state["attempts"][step.name] = attempt
            self._write_state(state_path, state)
            bundle.ledger.record(
                stage_id=step.stage_id,
                actor=step.actor,
                event_type="condition.step.started",
                time_category="orchestration_overhead",
                duration_ms=0,
                status="started",
                payload={"step": step.name, "attempt": attempt, "condition_id": assignment.condition_id},
                tool=self._condition_tool(assignment),
            )
            try:
                started = time.monotonic_ns()
                ledger_lines_before = self._ledger_line_count(bundle)
                result = self.backend.execute_step(
                    StepContext(
                        assignment,
                        bundle,
                        step,
                        attempt,
                        lease.path,
                        lease.branch,
                        f"{assignment.run_id}:{step.name}:{attempt}",
                        self._deadline_epoch_ms(bundle, state),
                        f"condition-accounting:{assignment.run_id}:{step.name}:{attempt}",
                    )
                )
                if not isinstance(result, StepResult):
                    raise TypeError("condition backend must return StepResult")
            except RetryableConditionError as exc:
                result = StepResult.retry(type(exc).__name__)
            except Exception as exc:
                result = StepResult("invalid-measurement", reason=type(exc).__name__)
            duration_ms = (time.monotonic_ns() - started) / 1_000_000
            if not self._has_backend_timing_evidence(
                bundle, ledger_lines_before, step=step, accounting_tool=(
                    f"condition-accounting:{assignment.run_id}:{step.name}:{attempt}"
                )
            ):
                result = StepResult("invalid-measurement", reason="missing-backend-timing-evidence")

            if result.status == "completed":
                try:
                    self._validate_artifacts(bundle, result.artifacts)
                except (OSError, ValueError) as exc:
                    failure = {"step": step.name, "reason": type(exc).__name__}
                    return ExecutionOutcome("INVALID_MEASUREMENT", failure=failure)
                state.setdefault("artifacts", []).extend(result.artifacts)
                if result.completion_proof is not None:
                    state["completion_proof"] = dict(result.completion_proof)
                bundle.ledger.record(
                    stage_id=step.stage_id,
                    actor=step.actor,
                    event_type="condition.step.completed",
                    time_category="orchestration_overhead",
                    duration_ms=0,
                    status="completed",
                    payload={
                        "step": step.name,
                        "attempt": attempt,
                        "backend_wall_clock_ms": round(duration_ms, 3),
                        "metadata": dict(result.metadata or {}),
                    },
                    tool=self._condition_tool(assignment),
                    artifact_refs=[artifact["path"] for artifact in result.artifacts],
                )
                limit = self._limit_outcome(bundle, state)
                if limit is not None:
                    return limit
                return None
            if result.status == "retry" and attempt < self.max_attempts:
                bundle.ledger.record(
                    stage_id=step.stage_id,
                    actor="fixer",
                    event_type="condition.step.retry",
                    time_category="orchestration_overhead",
                    duration_ms=0,
                    status="completed",
                    payload={"step": step.name, "attempt": attempt, "reason": result.reason},
                    tool=self.runner_tool,
                )
                limit = self._limit_outcome(bundle, state)
                if limit is not None:
                    return limit
                delay = self.retry_backoff_seconds * (2 ** (attempt - 1))
                started_wait = time.monotonic_ns()
                self.sleeper(delay)
                waited_ms = (time.monotonic_ns() - started_wait) / 1_000_000
                bundle.ledger.record(
                    stage_id=step.stage_id,
                    actor="infrastructure",
                    event_type="condition.retry.backoff",
                    time_category="external_wait",
                    duration_ms=waited_ms,
                    status="completed",
                    payload={"attempt": attempt, "scheduled_seconds": delay},
                    tool=self.runner_tool,
                )
                limit = self._limit_outcome(bundle, state)
                if limit is not None:
                    return limit
                continue

            terminal = {
                "human-required": "HUMAN_REQUIRED",
                "retry": "INFRASTRUCTURE_FAILURE",
                "timeout": "TIMEOUT",
                "budget-exceeded": "BUDGET_EXCEEDED",
                "invalid-measurement": "INVALID_MEASUREMENT",
                "failed": "FAILED",
            }[result.status]
            failure = {"step": step.name, "attempt": attempt, "reason": result.reason}
            bundle.ledger.record(
                stage_id=step.stage_id,
                actor=step.actor,
                event_type="condition.step.terminal",
                time_category="orchestration_overhead",
                duration_ms=0,
                status="blocked" if terminal == "HUMAN_REQUIRED" else "failed",
                payload={**failure, "terminal_state": terminal},
                tool=self.runner_tool,
            )
            return ExecutionOutcome(terminal, tuple(state.get("artifacts", [])), failure)
        raise AssertionError("unreachable retry loop")

    @staticmethod
    def _valid_completion_proof(proof: Mapping[str, Any]) -> bool:
        gates = proof.get("verified_gates")
        merge_commit = proof.get("merge_commit")
        score = proof.get("product_quality_score")
        return (
            isinstance(gates, list)
            and set(gates) == REQUIRED_QUALITY_GATES
            and isinstance(merge_commit, str)
            and len(merge_commit) == 40
            and all(character in "0123456789abcdef" for character in merge_commit)
            and isinstance(score, (int, float))
            and not isinstance(score, bool)
            and score >= 80
        )

    @staticmethod
    def _valid_pre_merge_proof(proof: Mapping[str, Any]) -> bool:
        gates = proof.get("verified_gates")
        score = proof.get("product_quality_score")
        return (
            isinstance(gates, list)
            and set(gates) == PRE_MERGE_QUALITY_GATES
            and isinstance(score, (int, float))
            and not isinstance(score, bool)
            and score >= 80
        )

    @staticmethod
    def _validate_artifacts(bundle: PreparedRunBundle, artifacts: tuple[dict[str, str], ...]) -> None:
        root = bundle.directory.resolve()
        for artifact in artifacts:
            path = artifact.get("path")
            digest = artifact.get("sha256")
            visibility = artifact.get("visibility")
            if (
                not isinstance(path, str)
                or not isinstance(digest, str)
                or visibility not in {"public", "private", "redacted"}
            ):
                raise ValueError("artifact requires path, sha256, and visibility")
            relative = Path(path)
            if relative.is_absolute() or ".." in relative.parts or len(digest) != 64 or any(
                character not in "0123456789abcdef" for character in digest
            ):
                raise ValueError("artifact path or digest is invalid")
            target = (root / path).resolve()
            if not target.is_relative_to(root):
                raise ValueError("artifact escapes the run bundle")
            if visibility == "private":
                if target.exists():
                    raise ValueError("private artifact content cannot exist in the public run bundle")
                continue
            if not target.is_file():
                raise ValueError("artifact must be a file inside the run bundle")
            if hashlib.sha256(target.read_bytes()).hexdigest() != digest:
                raise ValueError("artifact digest mismatch")

    @staticmethod
    def _limit_outcome(bundle: PreparedRunBundle, state: Mapping[str, Any]) -> ExecutionOutcome | None:
        budgets = bundle.manifest.get("budgets", {})
        if not isinstance(budgets, Mapping):
            return ExecutionOutcome("INVALID_MEASUREMENT", failure={"reason": "invalid-budget-contract"})
        if bundle.manifest.get("gate_mode") == "official-collection":
            numeric = REQUIRED_BUDGET_KEYS - {"stage_effective_work_ms"}
            stage_limits = budgets.get("stage_effective_work_ms")
            if (
                not REQUIRED_BUDGET_KEYS.issubset(budgets)
                or any(
                    not isinstance(budgets.get(key), (int, float))
                    or isinstance(budgets.get(key), bool)
                    or not math.isfinite(float(budgets[key]))
                    or budgets[key] <= 0
                    for key in numeric
                )
                or not isinstance(stage_limits, Mapping)
                or set(stage_limits) != {step.stage_id for step in CONDITION_STEPS}
                or any(
                    not isinstance(value, (int, float))
                    or isinstance(value, bool)
                    or not math.isfinite(float(value))
                    or value <= 0
                    for value in stage_limits.values()
                )
            ):
                return ExecutionOutcome("INVALID_MEASUREMENT", failure={"reason": "missing-frozen-budgets"})
        events = []
        if bundle.ledger.path.is_file():
            events = [json.loads(line) for line in bundle.ledger.path.read_text().splitlines() if line.strip()]
        if bundle.manifest.get("gate_mode") == "official-collection" and any(
            event.get("event_type") == "backend.attempt.effective-work"
            and event.get("token_cost_accounting_observed") is not True
            for event in events
        ):
            return ExecutionOutcome(
                "INVALID_MEASUREMENT", failure={"reason": "token-cost-accounting-unavailable"},
            )
        effective_ms = sum(
            float(event.get("duration_ms", 0))
            for event in events if event.get("time_category") == "effective_work"
        )
        external_wait_ms = sum(
            float(event.get("duration_ms", 0))
            for event in events if event.get("time_category") == "external_wait"
        )
        tokens = sum(
            sum(int(value) for value in event.get("tokens", {}).values())
            for event in events if isinstance(event.get("tokens"), Mapping)
        )
        cost_usd = sum(float(event.get("cost_usd", 0)) for event in events)
        elapsed_ms = time.time() * 1000 - float(state["started_at_epoch_ms"])
        if not all(math.isfinite(value) for value in (effective_ms, external_wait_ms, float(tokens), cost_usd, elapsed_ms)):
            return ExecutionOutcome("INVALID_MEASUREMENT", failure={"reason": "non-finite-measurement"})
        wall_limit = budgets.get("wall_time_ms")
        if isinstance(wall_limit, (int, float)) and elapsed_ms > wall_limit:
            return ExecutionOutcome("TIMEOUT", failure={"reason": "wall-time-limit"})
        checks = {
            "effective_work_ms": effective_ms,
            "external_wait_ms": external_wait_ms,
            "tokens": tokens,
            "cost_usd": cost_usd,
        }
        for key, observed in checks.items():
            limit = budgets.get(key)
            if isinstance(limit, (int, float)) and observed > limit:
                return ExecutionOutcome("BUDGET_EXCEEDED", failure={"reason": key})
        stage_limits = budgets.get("stage_effective_work_ms")
        if isinstance(stage_limits, Mapping):
            for stage, limit in stage_limits.items():
                observed = sum(
                    float(event.get("duration_ms", 0))
                    for event in events
                    if event.get("stage_id") == stage and event.get("time_category") == "effective_work"
                )
                if isinstance(limit, (int, float)) and observed > limit:
                    return ExecutionOutcome("BUDGET_EXCEEDED", failure={"reason": f"stage:{stage}"})
        return None

    @staticmethod
    def _validate_manifest_identity(assignment: MatrixAssignment, bundle: PreparedRunBundle) -> None:
        expected = {
            "run_id": assignment.run_id,
            "task_id": assignment.task_id,
            "product_id": assignment.product_id,
            "condition_id": assignment.condition_id,
            "replicate": assignment.replicate,
            "randomization_seed": assignment.randomization_seed,
        }
        if any(bundle.manifest.get(key) != value for key, value in expected.items()):
            raise RuntimeError("assignment and run manifest identity mismatch")

    @staticmethod
    def _deadline_epoch_ms(bundle: PreparedRunBundle, state: Mapping[str, Any]) -> float | None:
        budgets = bundle.manifest.get("budgets", {})
        limit = budgets.get("wall_time_ms") if isinstance(budgets, Mapping) else None
        if not isinstance(limit, (int, float)):
            return None
        return float(state["started_at_epoch_ms"]) + float(limit)

    @staticmethod
    def _ledger_line_count(bundle: PreparedRunBundle) -> int:
        if not bundle.ledger.path.is_file():
            return 0
        return sum(1 for line in bundle.ledger.path.read_text().splitlines() if line.strip())

    @staticmethod
    def _has_backend_timing_evidence(
        bundle: PreparedRunBundle,
        prior_count: int,
        *,
        step: ConditionStep,
        accounting_tool: str,
    ) -> bool:
        if not bundle.ledger.path.is_file():
            return False
        lines = [line for line in bundle.ledger.path.read_text().splitlines() if line.strip()]
        observed: set[str] = set()
        accounting_complete = False
        for line in lines[prior_count:]:
            event = json.loads(line)
            if (
                event.get("tool") == accounting_tool
                and event.get("stage_id") == step.stage_id
                and event.get("status") == "completed"
                and event.get("event_type") in {
                    "backend.attempt.effective-work",
                    "backend.attempt.external-wait",
                }
            ):
                observed.add(str(event["event_type"]))
                if event["event_type"] == "backend.attempt.effective-work":
                    tokens = event.get("tokens")
                    accounting_complete = (
                        isinstance(tokens, Mapping)
                        and set(tokens) == {"input", "output", "cached", "reasoning"}
                        and isinstance(event.get("cost_usd"), (int, float))
                    )
        return observed == {
            "backend.attempt.effective-work",
            "backend.attempt.external-wait",
        } and accounting_complete

    def _load_or_create_state(
        self,
        path: Path,
        assignment: MatrixAssignment,
        bundle: PreparedRunBundle,
    ) -> dict[str, Any]:
        if path.exists():
            state = json.loads(path.read_text(encoding="utf-8"))
            if (
                state.get("schema_version") != self.state_schema_version
                or state.get("run_id") != assignment.run_id
                or state.get("condition_id") != assignment.condition_id
                or state.get("factors") != self._factors(assignment)
                or state.get("task_manifest_sha256") != bundle.manifest.get("task_manifest_sha256")
                or bundle.manifest.get("condition_id") != assignment.condition_id
            ):
                raise RuntimeError("condition runner state identity mismatch")
            worktree = state.get("worktree")
            if isinstance(worktree, Mapping) and worktree.get("base_commit") != bundle.manifest.get("base_commit"):
                raise RuntimeError("condition runner base commit mismatch")
            return state
        state = {
            "schema_version": self.state_schema_version,
            "run_id": assignment.run_id,
            "condition_id": assignment.condition_id,
            "factors": self._factors(assignment),
            "task_manifest_sha256": bundle.manifest.get("task_manifest_sha256"),
            "worktree": None,
            "worktree_event_recorded": False,
            "completed_steps": [],
            "attempts": {},
            "current_step": None,
            "terminal_state": None,
            "failure": None,
            "started_at_epoch_ms": time.time() * 1000,
            "cleanup_pending": False,
            "worktree_release_event_recorded": False,
            "artifacts": [],
        }
        self._write_state(path, state)
        return state

    def _factors(self, assignment: MatrixAssignment) -> dict[str, Any]:
        return {
            "ade": assignment.ade,
            "harness": assignment.harness,
            "agentskit": assignment.agentskit,
        }

    def _condition_tool(self, assignment: MatrixAssignment) -> str:
        return f"condition-runner:{assignment.ade}:{assignment.harness}:{assignment.agentskit}"

    @staticmethod
    def _lease(state: Mapping[str, Any], *, require_path: bool = True) -> WorktreeLease | None:
        value = state.get("worktree")
        if not isinstance(value, Mapping):
            return None
        lease = WorktreeLease(
            path=Path(str(value["path"])),
            branch=str(value["branch"]),
            base_commit=str(value["base_commit"]),
        )
        if require_path and not lease.path.is_dir():
            raise RuntimeError("persisted worktree is missing")
        return lease

    @staticmethod
    def _write_state(path: Path, state: Mapping[str, Any]) -> None:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", delete=False
        ) as stream:
            temporary = Path(stream.name)
            stream.write(json.dumps(dict(state), indent=2, sort_keys=True) + "\n")
        temporary.replace(path)


class ComposedCollectionBackend:
    """Wire the persistent runner into ``PilotCollectionCoordinator``."""

    def __init__(
        self,
        worktrees: WorktreeProvider,
        backend_factory: Callable[[MatrixAssignment, PreparedRunBundle], ConditionStepBackend],
        verifier_factory: Callable[[MatrixAssignment, PreparedRunBundle], CompletionVerifier],
        *,
        max_attempts: int = 3,
        retry_backoff_seconds: float = 1.0,
    ) -> None:
        self.worktrees = worktrees
        self.backend_factory = backend_factory
        self.verifier_factory = verifier_factory
        self.max_attempts = max_attempts
        self.retry_backoff_seconds = retry_backoff_seconds

    def execute(self, assignment: MatrixAssignment, bundle: PreparedRunBundle) -> ExecutionOutcome:
        return ComposedConditionRunner(
            self.backend_factory(assignment, bundle),
            self.worktrees,
            self.verifier_factory(assignment, bundle),
            max_attempts=self.max_attempts,
            retry_backoff_seconds=self.retry_backoff_seconds,
        ).execute(assignment, bundle)
