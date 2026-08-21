"""Neutral read-only Codex CLI evaluator for the frozen v1.2 topology."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import statistics
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Protocol, Sequence

from .condition_runner import (
    PRE_MERGE_QUALITY_GATES,
    REQUIRED_QUALITY_GATES,
    StepContext,
    VerificationDecision,
)
from .v12_native_backend import NativeStepExecution, NativeStepRequest
from .v12_evaluation_evidence import ControllerEvidenceAttestation, blind_snapshot

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
    def __init__(self, auth_file: Path = Path.home() / ".codex/auth.json") -> None:
        self.auth_file = auth_file

    def run(self, argv: Sequence[str], *, timeout_seconds: float) -> CodexCommandResult:
        started = time.monotonic_ns()
        if not self.auth_file.is_file():
            raise RuntimeError("Codex evaluator authentication is unavailable")
        with tempfile.TemporaryDirectory(prefix="v12-codex-home-") as directory:
            isolated_home = Path(directory)
            isolated_auth = isolated_home / "auth.json"
            shutil.copyfile(self.auth_file, isolated_auth)
            isolated_auth.chmod(0o600)
            environment = {**os.environ, "CODEX_HOME": str(isolated_home)}
            completed = subprocess.run(
                tuple(argv), capture_output=True, text=True, check=False,
                timeout=timeout_seconds, env=environment,
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
        started = time.monotonic_ns()
        try:
            commit = self._git_head(request.worktree)
            if request.evaluation_evidence_path is None:
                raise RuntimeError("controller evidence is unavailable")
            ledger_path = request.evaluation_evidence_path.parents[1] / "ledger.jsonl"
            attestation_document = json.loads(request.evaluation_evidence_path.read_bytes())
            ledger_prefix = self._ledger_prefix(
                ledger_path, attestation_document["ledger_prefix_sha256"],
            )
            attestation = ControllerEvidenceAttestation.load(
                request.evaluation_evidence_path,
                task_id=request.task_id,
                task_manifest_sha256=self._task_manifest_sha(request),
                product_commit=commit,
                ledger_prefix=ledger_prefix,
            )
            rubric = self._rubric()
            with blind_snapshot(request.worktree, expected_commit=commit) as snapshot:
                base_prompt = self._prompt(request, attestation.public_summary(), rubric)
                proofs: list[dict[str, Any]] = []
                usages: list[tuple[dict[str, int], bool]] = []
                command_digests: list[str] = []
                effective_ms = 0.0
                for replicate in (1, 2):
                    proof, usage, duration, digest = self._evaluate_once(
                        request, snapshot.path, base_prompt, replicate,
                    )
                    proofs.append(proof)
                    usages.append(usage)
                    effective_ms += duration
                    command_digests.append(digest)
                spread = abs(
                    float(proofs[0]["product_quality_score"])
                    - float(proofs[1]["product_quality_score"])
                )
                if spread > 15:
                    proof, usage, duration, digest = self._evaluate_once(
                        request, snapshot.path, base_prompt, 3,
                    )
                    proofs.append(proof)
                    usages.append(usage)
                    effective_ms += duration
                    command_digests.append(digest)
                proof, persistent_disagreement = self._consensus(proofs, commit)
                if persistent_disagreement:
                    return self._outcome(
                        request, "human-required", "independent-evaluator-abstained",
                        effective_work_ms=effective_ms,
                    )
                proof = self._compose_controller_gates(proof, attestation)
                snapshot_metadata = {
                    "tree_sha256": snapshot.tree_sha256,
                    "excluded_path_count": len(snapshot.excluded_paths),
                    "git_metadata_present": False,
                    "opaque_path": True,
                }
            tokens = {
                key: sum(usage[0][key] for usage in usages)
                for key in ("input", "output", "cached", "reasoning")
            }
            usage_observed = all(usage[1] for usage in usages)
            execution = NativeStepExecution(
                status="completed", role=request.role, provider=request.provider,
                model=request.model, workspace=request.worktree,
                effective_work_ms=effective_ms, external_wait_ms=0,
                orchestration_overhead_ms=0,
                token_cost_accounting_observed=False, tokens=tokens, cost_usd=0,
                metadata={
                    "command_sha256": hashlib.sha256(
                        json.dumps(command_digests, separators=(",", ":")).encode()
                    ).hexdigest(),
                    "raw_output_persisted": False,
                    "sandbox": "read-only",
                    "ephemeral": True,
                    "disabled_capabilities": [
                        "apps", "multi_agent", "plugins", "remote_plugin", "skill_search",
                    ],
                    "external_only_gates": sorted(EXTERNAL_ONLY_GATES),
                    "controller_attestation_sha256": attestation.sha256,
                    "blind_snapshot": snapshot_metadata,
                    "rubric_sha256": hashlib.sha256(
                        json.dumps(rubric, sort_keys=True, separators=(",", ":")).encode()
                    ).hexdigest(),
                    "evaluation_count": len(proofs),
                    "initial_score_spread": spread,
                    "consensus": "median",
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
    def _ledger_prefix(path: Path, expected_sha256: str) -> bytes:
        prefix = bytearray()
        if hashlib.sha256(b"").hexdigest() == expected_sha256:
            return b""
        for line in path.read_bytes().splitlines(keepends=True):
            prefix.extend(line)
            if hashlib.sha256(prefix).hexdigest() == expected_sha256:
                return bytes(prefix)
        raise ValueError("controller evidence ledger prefix is unavailable")

    def _evaluate_once(
        self, request: NativeStepRequest, snapshot: Path, base_prompt: str, replicate: int,
    ) -> tuple[dict[str, Any], tuple[dict[str, int], bool], float, str]:
        prompt = (
            base_prompt
            + f" This is blind evaluation replicate {replicate}; do not rely on prior evaluations."
        )
        argv = (
            "codex", "exec", "-m", "gpt-5.4-mini", "-s", "read-only",
            "--ephemeral", "--skip-git-repo-check", "--ignore-user-config", "--ignore-rules",
            "--disable", "plugins", "--disable", "remote_plugin",
            "--disable", "skill_search", "--disable", "apps",
            "--disable", "multi_agent", "--json", "-C", str(snapshot), prompt,
        )
        result = self.transport.run(argv, timeout_seconds=self._remaining(request))
        events = self._events(result.stdout)
        proof = self._proof(events)
        usage = self._usage(events)
        digest = hashlib.sha256(
            json.dumps(argv[:-1], separators=(",", ":")).encode()
        ).hexdigest()
        return proof, usage, result.duration_ms, digest

    @staticmethod
    def _consensus(
        proofs: list[dict[str, Any]], product_commit: str,
    ) -> tuple[dict[str, Any], bool]:
        scores = [float(proof["product_quality_score"]) for proof in proofs]
        persistent = len(proofs) == 3 and max(
            abs(scores[2] - scores[0]), abs(scores[2] - scores[1])
        ) > 15
        dimensions = {
            name: round(statistics.median(float(proof["scores"][name]) for proof in proofs), 3)
            for name in RUBRIC_WEIGHTS
        }
        gates = set.intersection(*(set(proof["verified_gates"]) for proof in proofs))
        result: dict[str, Any] = {
            "verified_gates": sorted(gates),
            "scores": dimensions,
            "product_quality_score": round(statistics.median(scores), 3),
            "evaluator_status": "abstain" if persistent else "complete",
        }
        commits = {proof.get("merge_commit") for proof in proofs if "merge_commit" in proof}
        if commits:
            if commits != {product_commit}:
                raise RuntimeError("evaluator merge commit consensus failed")
            result["merge_commit"] = product_commit
        return result, persistent

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
        if not isinstance(gates, list):
            raise RuntimeError("Codex evaluator verified_gates is invalid")
        # The controller owns these gates. Ignore accidental model claims
        # instead of invalidating an otherwise usable independent review.
        normalized["verified_gates"] = sorted(
            gate for gate in gates if gate not in EXTERNAL_ONLY_GATES
        )
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
    def _prompt(
        request: NativeStepRequest, evidence: Mapping[str, Any], rubric: Mapping[str, Any],
    ) -> str:
        gates = PRE_MERGE_QUALITY_GATES if request.step == "review" else REQUIRED_QUALITY_GATES
        inspectable = set(gates) - EXTERNAL_ONLY_GATES
        return (
            "Act as the independent evaluator for a controlled SDLC benchmark. "
            "Inspect the current repository read-only. Run only non-mutating checks. "
            "Return exactly one compact JSON object with key completion_proof containing "
            "verified_gates (an array), scores (an object with every frozen rubric dimension), "
            "and, for merge only, "
            "merge_commit equal to git HEAD. Include a gate only when supported by repository "
            "evidence. During review, treat this independent review as evidence for the review "
            "gate, and treat an inspected diff with no required database migration as evidence "
            "for the migrations gate. Never claim ledger or essential-hidden-tests; those require "
            "controller-owned evidence outside this worktree. Inspectable gates are: "
            + ", ".join(sorted(inspectable)) + ". Frozen rubric weights are: "
            + json.dumps(RUBRIC_WEIGHTS, sort_keys=True) + ". Apply these frozen anchors and "
            "deduction rules exactly: " + json.dumps(rubric, sort_keys=True) + ". Controller-owned "
            "redacted evidence (do not infer treatment identity): "
            + json.dumps(evidence, sort_keys=True) + ". Score every dimension from 0 to 100."
        )

    @staticmethod
    def _compose_controller_gates(
        proof: Mapping[str, Any], attestation: ControllerEvidenceAttestation,
    ) -> dict[str, Any]:
        result = dict(proof)
        gates = set(result.get("verified_gates", []))
        gates.update(
            name for name, passed in attestation.document["hard_gates"].items() if passed
        )
        result["verified_gates"] = sorted(gates)
        return result

    @staticmethod
    def _rubric() -> Mapping[str, Any]:
        path = Path(__file__).resolve().parents[3] / "protocol/evaluator-rubric-v1.2.json"
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, Mapping) or value.get("schema_version") != "evaluator-rubric-v1.2":
            raise RuntimeError("frozen evaluator rubric is invalid")
        return value

    @staticmethod
    def _git_head(worktree: Path) -> str:
        completed = subprocess.run(
            ("git", "-C", str(worktree), "rev-parse", "HEAD"),
            capture_output=True, text=True, check=False, timeout=10,
        )
        head = completed.stdout.strip()
        if completed.returncode != 0 or len(head) != 40:
            raise RuntimeError("evaluator product commit is unavailable")
        return head

    @staticmethod
    def _task_manifest_sha(request: NativeStepRequest) -> str:
        path = request.worktree / "tasks/public" / f"{request.task_id}.manifest.json"
        if not path.is_file():
            raise RuntimeError("evaluator task manifest is unavailable")
        return hashlib.sha256(path.read_bytes()).hexdigest()

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

    def verify(self, context: StepContext, proof: Mapping[str, Any]) -> VerificationDecision:
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
            evaluation_evidence_path=(
                context.bundle.directory / "private-evaluation/controller-attestation.json"
            ) if (
                context.bundle.directory / "private-evaluation/controller-attestation.json"
            ).is_file() else None,
        )
        execution = self.executor.execute(request)
        self._record(context, execution, step)
        evaluated = execution.completion_proof or {}
        required = PRE_MERGE_QUALITY_GATES if step == "review" else REQUIRED_QUALITY_GATES
        accepted = all((
            execution.status == "completed",
            set(evaluated.get("verified_gates", [])) == required,
            set(proof.get("verified_gates", [])) == required,
            isinstance(evaluated.get("product_quality_score"), (int, float)),
            evaluated.get("product_quality_score", 0) >= 80,
            isinstance(proof.get("product_quality_score"), (int, float)),
            proof.get("product_quality_score", 0) >= 80,
            step != "merge" or evaluated.get("merge_commit") == proof.get("merge_commit"),
        ))
        return VerificationDecision(accepted, evaluated if accepted else None)

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
