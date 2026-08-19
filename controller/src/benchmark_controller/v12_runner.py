"""Native v1.2 condition runner contracts and integrity-bound role handoffs."""

from __future__ import annotations

from dataclasses import replace
import hashlib
import json
from pathlib import Path
import tempfile
import time
from typing import Any, Callable, Mapping

from .condition_runner import (
    ComposedConditionRunner,
    CompletionVerifier,
    ConditionStepBackend,
    StepContext,
    StepResult,
    WorktreeProvider,
)
from .collection import ExecutionOutcome
from .matrix import MatrixAssignment
from .run_bundles import PreparedRunBundle
from .v12_evidence_collector import ControllerEvidenceCollector

HANDOFF_RELATIVE = Path("runtime-control/handoffs/codex-to-grok.json")
AGENTSKIT_CONTEXT_RELATIVE = Path("runtime-control/agentskit/context.json")
HANDOFF_KEYS = {"requirements", "implementation_plan", "acceptance_criteria"}
PUBLIC_AGENTSKIT_COMPONENTS = {"doc-bridge", "playbook", "code-review"}
AGENTSKIT_EVIDENCE_KEYS = {
    "source_commit", "command_sha256", "output_sha256", "exit_code", "workspace",
}


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _atomic_json(path: Path, value: Mapping[str, Any]) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = (json.dumps(dict(value), indent=2, sort_keys=True) + "\n").encode()
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix=f".{path.name}.", delete=False) as stream:
        temporary = Path(stream.name)
        stream.write(encoded)
    temporary.replace(path)
    return _sha(encoded)


class V12NativeConditionRunner(ComposedConditionRunner):
    """v1.2 state machine: harness-free and crash-invalidating by design."""

    state_schema_version = "condition-runner-state-v1.2"
    runner_tool = "condition-runner-v1.2"
    accepts_v12 = True

    def __init__(
        self,
        backend: ConditionStepBackend,
        worktrees: WorktreeProvider,
        verifier: CompletionVerifier,
        evidence_collector: ControllerEvidenceCollector | None = None,
        **kwargs: Any,
    ) -> None:
        if (
            getattr(verifier, "provider", None),
            getattr(verifier, "model", None),
        ) != ("codex", "gpt-5.4-mini"):
            raise ValueError("v1.2 requires the frozen independent evaluator")
        super().__init__(backend, worktrees, verifier, **kwargs)
        self.evidence_collector = evidence_collector or ControllerEvidenceCollector()

    def _prepare_step(self, context: StepContext) -> None:
        if context.step.name == "review":
            self.evidence_collector.collect_for(context)

    def _prepare_verification(self, context: StepContext) -> None:
        self.evidence_collector.collect_for(context)

    def _factors(self, assignment: MatrixAssignment) -> dict[str, Any]:
        if assignment.harness is not None:
            raise RuntimeError("v1.2 native runner prohibits an independent harness factor")
        return {"ade": assignment.ade, "agentskit": assignment.agentskit}

    def _condition_tool(self, assignment: MatrixAssignment) -> str:
        return f"condition-runner-v1.2:{assignment.ade}:{assignment.agentskit}"


class V12HandoffBackend:
    """Decorate an ADE backend with mandatory factor and role handoff evidence."""

    supports_idempotent_replay = True
    enforces_deadline = True

    def __init__(
        self,
        delegate: ConditionStepBackend,
        *,
        agentskit_context_factory: Callable[[StepContext], Mapping[str, Any]] | None = None,
        agentskit_evidence_verifier: Callable[[StepContext, Mapping[str, Any]], bool] | None = None,
    ) -> None:
        if getattr(delegate, "supports_idempotent_replay", False) is not True:
            raise ValueError("v1.2 ADE backend must support idempotent replay")
        if getattr(delegate, "enforces_deadline", False) is not True:
            raise ValueError("v1.2 ADE backend must enforce deadlines")
        self.delegate = delegate
        self.agentskit_context_factory = agentskit_context_factory
        self.agentskit_evidence_verifier = agentskit_evidence_verifier
        self._factor_digest: str | None = None
        self._handoff_digest: str | None = None

    def execute_step(self, context: StepContext) -> StepResult:
        if context.assignment.harness is not None:
            return StepResult("invalid-measurement", reason="v1.2-harness-factor-present")
        factor_path = context.bundle.directory / AGENTSKIT_CONTEXT_RELATIVE
        handoff_path = context.bundle.directory / HANDOFF_RELATIVE
        factor_digest = self._prepare_factor(context, factor_path)

        enriched = replace(
            context,
            handoff_path=handoff_path if handoff_path.is_file() else None,
            agentskit_context_path=factor_path if factor_path.is_file() else None,
        )
        if context.step.name == "implementation":
            try:
                handoff_digest = self._validate_handoff(context, handoff_path)
            except (OSError, RuntimeError, ValueError) as exc:
                return StepResult("invalid-measurement", reason=str(exc))
            enriched = replace(enriched, handoff_path=handoff_path)
        else:
            handoff_digest = None

        ledger_before = context.bundle.ledger.path.read_text() if context.bundle.ledger.path.exists() else ""
        result = self.delegate.execute_step(enriched)
        if context.assignment.agentskit == "on" and (
            not factor_path.is_file() or _sha(factor_path.read_bytes()) != self._factor_digest
        ):
            return StepResult("invalid-measurement", reason="agentskit-context-mutated-by-delegate")
        if self._handoff_digest is not None and (
            not handoff_path.is_file() or _sha(handoff_path.read_bytes()) != self._handoff_digest
        ):
            return StepResult("invalid-measurement", reason="planner-handoff-mutated-by-delegate")
        if context.assignment.agentskit == "off" and self._agentskit_events_added(context, ledger_before):
            return StepResult("invalid-measurement", reason="agentskit-off-ledger-contamination")
        if context.assignment.agentskit == "off" and (
            factor_path.exists() or (context.worktree / ".benchmark/agentskit").exists()
        ):
            return StepResult("invalid-measurement", reason="agentskit-off-file-contamination")
        if result.status != "completed":
            return result
        metadata = dict(result.metadata or {})

        if context.step.name == "decomposition":
            payload = metadata.pop("handoff_payload", None)
            try:
                digest = self._write_handoff(context, handoff_path, payload)
            except (OSError, RuntimeError, ValueError) as exc:
                return StepResult("invalid-measurement", reason=str(exc))
            metadata["handoff_sha256"] = digest
        elif context.step.name == "implementation":
            if metadata.get("handoff_sha256_observed") != handoff_digest:
                return StepResult("invalid-measurement", reason="executor-handoff-acknowledgement-mismatch")

        if context.assignment.agentskit == "on" and context.step.name in {"decomposition", "implementation"}:
            if metadata.get("agentskit_context_sha256_observed") != factor_digest:
                return StepResult("invalid-measurement", reason="agentskit-context-acknowledgement-mismatch")
            if set(metadata.get("agentskit_components_observed", [])) != PUBLIC_AGENTSKIT_COMPONENTS:
                return StepResult("invalid-measurement", reason="agentskit-component-acknowledgement-mismatch")

        return StepResult.completed(
            artifacts=result.artifacts,
            metadata=metadata,
            completion_proof=result.completion_proof,
        )

    def close(self) -> None:
        close = getattr(self.delegate, "close", None)
        if callable(close):
            close()

    def _prepare_factor(self, context: StepContext, path: Path) -> str | None:
        if context.assignment.agentskit == "off":
            if path.exists():
                raise RuntimeError("AgentsKit OFF worktree contains factor context")
            return None
        if context.assignment.agentskit != "on" or self.agentskit_context_factory is None:
            raise RuntimeError("AgentsKit ON has no public context factory")
        if self.agentskit_evidence_verifier is None:
            raise RuntimeError("AgentsKit ON has no independent execution-evidence verifier")
        if path.is_file():
            document = json.loads(path.read_text())
            if not self._valid_factor(context, document):
                raise RuntimeError("persisted AgentsKit context identity mismatch")
            if not self.agentskit_evidence_verifier(context, document):
                raise RuntimeError("AgentsKit native execution evidence was not independently verified")
            observed = _sha(path.read_bytes())
            if self._factor_digest != observed:
                raise RuntimeError("frozen runtime evidence digest mismatch")
            return observed
        payload = dict(self.agentskit_context_factory(context))
        if not self._valid_factor(context, payload):
            raise RuntimeError("AgentsKit context violates the public-only contract")
        if not self.agentskit_evidence_verifier(context, payload):
            raise RuntimeError("AgentsKit native execution evidence was not independently verified")
        digest = _atomic_json(path, payload)
        self._factor_digest = digest
        context.bundle.ledger.record(
            stage_id=context.step.stage_id,
            actor="controller",
            event_type="agentskit.factor.materialized",
            time_category="instrumentation_overhead",
            duration_ms=0,
            status="completed",
            payload={"context_sha256": digest, "components": sorted(PUBLIC_AGENTSKIT_COMPONENTS)},
            tool="agentskit-public-v1.2",
        )
        return digest

    @staticmethod
    def _valid_factor(context: StepContext, payload: Mapping[str, Any]) -> bool:
        executions = payload.get("executions")
        return all((
            payload.get("condition_id") == context.assignment.condition_id,
            payload.get("task_id") == context.assignment.task_id,
            payload.get("public_only") is True,
            payload.get("agentskit_os_used") is False,
            set(payload.get("components", [])) == PUBLIC_AGENTSKIT_COMPONENTS,
            isinstance(payload.get("guidance"), str) and bool(payload["guidance"].strip()),
            isinstance(executions, Mapping),
            set(executions or {}) == PUBLIC_AGENTSKIT_COMPONENTS,
            all(
                isinstance(record, Mapping)
                and set(record) == AGENTSKIT_EVIDENCE_KEYS
                and isinstance(record.get("source_commit"), str)
                and len(record["source_commit"]) == 40
                and all(character in "0123456789abcdef" for character in record["source_commit"])
                and isinstance(record.get("command_sha256"), str)
                and len(record["command_sha256"]) == 64
                and all(character in "0123456789abcdef" for character in record["command_sha256"])
                and isinstance(record.get("output_sha256"), str)
                and len(record["output_sha256"]) == 64
                and all(character in "0123456789abcdef" for character in record["output_sha256"])
                and record.get("exit_code") == 0
                and record.get("workspace") == str(context.worktree.resolve())
                for record in (executions or {}).values()
            ),
        ))

    @staticmethod
    def _agentskit_events_added(context: StepContext, before: str) -> bool:
        current = (
            context.bundle.ledger.path.read_text()
            if context.bundle.ledger.path.exists()
            else ""
        )
        suffix = current[len(before):] if current.startswith(before) else current
        for line in suffix.splitlines():
            event = json.loads(line)
            if "agentskit" in str(event.get("tool", "")).lower():
                return True
            if str(event.get("event_type", "")).startswith("agentskit."):
                return True
        return False

    def _write_handoff(self, context: StepContext, path: Path, payload: Any) -> str:
        if not isinstance(payload, Mapping) or set(payload) != HANDOFF_KEYS:
            raise ValueError("planner handoff payload is incomplete")
        if any(not isinstance(payload[key], (str, list, dict)) or not payload[key] for key in HANDOFF_KEYS):
            raise ValueError("planner handoff payload contains an empty section")
        envelope = {
            "schema_version": "codex-grok-handoff-v1.2",
            "condition_id": context.assignment.condition_id,
            "task_id": context.assignment.task_id,
            "task_manifest_sha256": context.bundle.manifest["task_manifest_sha256"],
            "base_commit": context.bundle.manifest["base_commit"],
            "from": {"role": "planner_requirements_lead", "provider": "codex-cli", "model": "gpt-5.4"},
            "to": {"role": "executor_fixer", "provider": "grok-cli", "model": "grok-4.5"},
            "payload": dict(payload),
        }
        digest = _atomic_json(path, envelope)
        self._handoff_digest = digest
        context.bundle.ledger.record(
            stage_id="decomposition",
            actor="planner",
            event_type="role.handoff.materialized",
            time_category="instrumentation_overhead",
            duration_ms=0,
            status="completed",
            payload={"handoff_sha256": digest, "from": "planner_requirements_lead", "to": "executor_fixer"},
            tool="condition-runner-v1.2",
        )
        return digest

    def _validate_handoff(self, context: StepContext, path: Path) -> str:
        document = json.loads(path.read_text())
        if not all((
            set(document) == {"schema_version", "condition_id", "task_id", "task_manifest_sha256", "base_commit", "from", "to", "payload"},
            document.get("schema_version") == "codex-grok-handoff-v1.2",
            document.get("condition_id") == context.assignment.condition_id,
            document.get("task_id") == context.assignment.task_id,
            document.get("task_manifest_sha256") == context.bundle.manifest["task_manifest_sha256"],
            document.get("base_commit") == context.bundle.manifest["base_commit"],
            document.get("from", {}).get("model") == "gpt-5.4",
            document.get("from", {}).get("provider") == "codex-cli",
            document.get("from", {}).get("role") == "planner_requirements_lead",
            document.get("to", {}).get("model") == "grok-4.5",
            document.get("to", {}).get("provider") == "grok-cli",
            document.get("to", {}).get("role") == "executor_fixer",
            isinstance(document.get("payload"), Mapping),
            set(document.get("payload", {})) == HANDOFF_KEYS,
        )):
            raise ValueError("planner handoff identity mismatch")
        observed = _sha(path.read_bytes())
        if self._handoff_digest != observed:
            raise RuntimeError("frozen runtime evidence digest mismatch")
        return observed


class V12NativeCollectionBackend:
    """Wire the v1.2-native runner into the collection coordinator."""

    def __init__(
        self,
        worktrees: WorktreeProvider,
        backend_factory: Callable[[MatrixAssignment, PreparedRunBundle], ConditionStepBackend],
        verifier_factory: Callable[[MatrixAssignment, PreparedRunBundle], CompletionVerifier],
        evidence_collector_factory: Callable[
            [MatrixAssignment, PreparedRunBundle], ControllerEvidenceCollector
        ] | None = None,
        *,
        max_attempts: int = 3,
        retry_backoff_seconds: float = 1.0,
    ) -> None:
        self.worktrees = worktrees
        self.backend_factory = backend_factory
        self.verifier_factory = verifier_factory
        self.evidence_collector_factory = evidence_collector_factory
        self.max_attempts = max_attempts
        self.retry_backoff_seconds = retry_backoff_seconds

    def execute(self, assignment: MatrixAssignment, bundle: PreparedRunBundle) -> ExecutionOutcome:
        backend = self.backend_factory(assignment, bundle)
        try:
            collector = (
                self.evidence_collector_factory(assignment, bundle)
                if self.evidence_collector_factory else ControllerEvidenceCollector()
            )
            return V12NativeConditionRunner(
                backend,
                self.worktrees,
                self.verifier_factory(assignment, bundle),
                evidence_collector=collector,
                max_attempts=self.max_attempts,
                retry_backoff_seconds=self.retry_backoff_seconds,
            ).execute(assignment, bundle)
        finally:
            close = getattr(backend, "close", None)
            if callable(close):
                started = time.monotonic_ns()
                cleanup_error: Exception | None = None
                try:
                    close()
                except Exception as exc:
                    cleanup_error = exc
                bundle.ledger.record(
                    stage_id="documentation", actor="infrastructure",
                    event_type="condition.backend.cleanup",
                    time_category="orchestration_overhead",
                    duration_ms=(time.monotonic_ns() - started) / 1_000_000,
                    status="failed" if cleanup_error else "completed",
                    payload={"condition_id": assignment.condition_id},
                    tool="condition-runner-v1.2",
                )
                if cleanup_error is not None:
                    raise cleanup_error
