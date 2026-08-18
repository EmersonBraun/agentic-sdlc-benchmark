"""Native v1.2 condition runner contracts and integrity-bound role handoffs."""

from __future__ import annotations

from dataclasses import replace
import hashlib
import json
from pathlib import Path
import tempfile
from typing import Any, Callable, Mapping

from .condition_runner import (
    ComposedConditionRunner,
    ConditionStepBackend,
    StepContext,
    StepResult,
)
from .matrix import MatrixAssignment

HANDOFF_RELATIVE = Path(".benchmark/handoffs/codex-to-grok.json")
AGENTSKIT_CONTEXT_RELATIVE = Path(".benchmark/agentskit/context.json")
HANDOFF_KEYS = {"requirements", "implementation_plan", "acceptance_criteria"}
PUBLIC_AGENTSKIT_COMPONENTS = {"doc-bridge", "playbook", "code-review"}


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
    ) -> None:
        if getattr(delegate, "supports_idempotent_replay", False) is not True:
            raise ValueError("v1.2 ADE backend must support idempotent replay")
        if getattr(delegate, "enforces_deadline", False) is not True:
            raise ValueError("v1.2 ADE backend must enforce deadlines")
        self.delegate = delegate
        self.agentskit_context_factory = agentskit_context_factory

    def execute_step(self, context: StepContext) -> StepResult:
        if context.assignment.harness is not None:
            return StepResult("invalid-measurement", reason="v1.2-harness-factor-present")
        factor_path = context.worktree / AGENTSKIT_CONTEXT_RELATIVE
        handoff_path = context.worktree / HANDOFF_RELATIVE
        factor_digest = self._prepare_factor(context, factor_path)

        enriched = replace(
            context,
            handoff_path=handoff_path if handoff_path.is_file() else None,
            agentskit_context_path=factor_path if factor_path.is_file() else None,
        )
        if context.step.name == "implementation":
            try:
                handoff_digest = self._validate_handoff(context, handoff_path)
            except (OSError, ValueError) as exc:
                return StepResult("invalid-measurement", reason=str(exc))
            enriched = replace(enriched, handoff_path=handoff_path)
        else:
            handoff_digest = None

        result = self.delegate.execute_step(enriched)
        if result.status != "completed":
            return result
        metadata = dict(result.metadata or {})

        if context.step.name == "decomposition":
            payload = metadata.pop("handoff_payload", None)
            try:
                digest = self._write_handoff(context, handoff_path, payload)
            except (OSError, ValueError) as exc:
                return StepResult("invalid-measurement", reason=str(exc))
            metadata["handoff_sha256"] = digest
        elif context.step.name == "implementation":
            if metadata.get("handoff_sha256_observed") != handoff_digest:
                return StepResult("invalid-measurement", reason="executor-handoff-acknowledgement-mismatch")

        if context.assignment.agentskit == "on" and context.step.name in {"decomposition", "implementation"}:
            if metadata.get("agentskit_context_sha256_observed") != factor_digest:
                return StepResult("invalid-measurement", reason="agentskit-context-acknowledgement-mismatch")

        return StepResult.completed(
            artifacts=result.artifacts,
            metadata=metadata,
            completion_proof=result.completion_proof,
        )

    def _prepare_factor(self, context: StepContext, path: Path) -> str | None:
        if context.assignment.agentskit == "off":
            if path.exists():
                raise RuntimeError("AgentsKit OFF worktree contains factor context")
            return None
        if context.assignment.agentskit != "on" or self.agentskit_context_factory is None:
            raise RuntimeError("AgentsKit ON has no public context factory")
        if path.is_file():
            document = json.loads(path.read_text())
            if not self._valid_factor(context, document):
                raise RuntimeError("persisted AgentsKit context identity mismatch")
            return _sha(path.read_bytes())
        payload = dict(self.agentskit_context_factory(context))
        if not self._valid_factor(context, payload):
            raise RuntimeError("AgentsKit context violates the public-only contract")
        digest = _atomic_json(path, payload)
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
        return all((
            payload.get("condition_id") == context.assignment.condition_id,
            payload.get("task_id") == context.assignment.task_id,
            payload.get("public_only") is True,
            payload.get("agentskit_os_used") is False,
            set(payload.get("components", [])) == PUBLIC_AGENTSKIT_COMPONENTS,
            isinstance(payload.get("guidance"), str) and bool(payload["guidance"].strip()),
        ))

    @staticmethod
    def _write_handoff(context: StepContext, path: Path, payload: Any) -> str:
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

    @staticmethod
    def _validate_handoff(context: StepContext, path: Path) -> str:
        document = json.loads(path.read_text())
        if not all((
            document.get("schema_version") == "codex-grok-handoff-v1.2",
            document.get("condition_id") == context.assignment.condition_id,
            document.get("task_id") == context.assignment.task_id,
            document.get("task_manifest_sha256") == context.bundle.manifest["task_manifest_sha256"],
            document.get("base_commit") == context.bundle.manifest["base_commit"],
            document.get("from", {}).get("model") == "gpt-5.4",
            document.get("to", {}).get("model") == "grok-4.5",
            isinstance(document.get("payload"), Mapping),
        )):
            raise ValueError("planner handoff identity mismatch")
        return _sha(path.read_bytes())
