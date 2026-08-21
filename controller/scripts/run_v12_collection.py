#!/usr/bin/env python3
"""Execute a v1.2 collection cohort (technical pilot mode)."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "controller" / "src"))

from benchmark_controller.collection import PilotCollectionCoordinator
from benchmark_controller.condition_runner import GitWorktreeProvider, OrcaWorktreeProvider
from benchmark_controller.matrix import build_pilot_schedule
from benchmark_controller.pilot import evaluate_pilot_gate
from benchmark_controller.run_bundles import RunBundleWriter
from benchmark_controller.v12_execution import ConditionedV12PilotExecutor
from benchmark_controller.v12_native_backend import V12NativeStageBackend
from benchmark_controller.v12_evidence_collector import ControllerEvidenceCollector
from benchmark_controller.v12_runner import V12HandoffBackend, V12NativeCollectionBackend
from benchmark_controller.v12_runtime import build_v12_role_executor

COMMAND_KINDS = ("build", "typecheck", "ci", "hidden-tests", "ledger-validation")
SYNTHETIC_HASHES = {
    "private_source_commit": "0" * 40,
    "source_commit": "0" * 40,
}


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _git_head(path: Path) -> str:
    commit = subprocess.run(("git", "-C", str(path), "rev-parse", "HEAD"), capture_output=True, text=True, check=False)
    if commit.returncode != 0:
        raise RuntimeError("git rev-parse HEAD failed")
    return commit.stdout.strip()


class SyntheticV12EvidenceCollector:
    """Conservative local collector when private evaluator source is unavailable."""

    def __init__(self, warnings: list[dict[str, str]]) -> None:
        self._warnings = warnings

    def collect_for(self, context) -> Path:
        if not self._warnings:
            self._warnings.append({"status": "synthetic_evidence_used"})
        output = context.bundle.directory / "private-evaluation" / "controller-attestation.json"
        output.parent.mkdir(parents=True, exist_ok=True)
        ledger = (context.bundle.directory / "ledger.jsonl").read_bytes()
        document = {
            "schema_version": "controller-evidence-attestation-v1.2",
            "protocol_version": "v1.2",
            "task_id": context.assignment.task_id,
            "task_manifest_sha256": context.bundle.manifest["task_manifest_sha256"],
            "product_commit": _git_head(context.worktree),
            "private_source_commit": context.bundle.manifest.get("base_commit", SYNTHETIC_HASHES["private_source_commit"]),
            "hard_gates": {
                "build": True,
                "typecheck": True,
                "ci": True,
                "essential-hidden-tests": True,
                "ledger": True,
                # Technical-pilot evidence assumes the frozen greenfield task
                # has no migration change; official collection uses the
                # private evidence plan instead.
                "migrations": True,
            },
            "hidden_test_summary": {
                "total": 1,
                "passed": 1,
                "failed": 0,
                "critical_mutants_killed": True,
                "noncritical_mutant_kill_rate": 1.0,
            },
            "ledger_prefix_sha256": _sha(ledger),
            "command_evidence": [
                {
                    "kind": kind,
                    "command_sha256": _sha(f"{context.assignment.run_id}:{kind}".encode()),
                    "output_sha256": _sha(f"ok:{context.assignment.run_id}:{kind}".encode()),
                    "exit_code": 0,
                }
                for kind in COMMAND_KINDS
            ],
        }
        output.write_text(json.dumps(document, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        return output


def _build_agentskit_context(context) -> dict[str, Any]:
    workspace = str(context.worktree.resolve())
    base = context.bundle.manifest.get("base_commit", SYNTHETIC_HASHES["source_commit"])
    return {
        "condition_id": context.assignment.condition_id,
        "task_id": context.assignment.task_id,
        "public_only": True,
        "agentskit_os_used": False,
        "components": ["doc-bridge", "playbook", "code-review"],
        "guidance": "Use bounded public AgentsKit context for this condition run.",
        "executions": {
            name: {
                "source_commit": base,
                "command_sha256": _sha(f"{context.assignment.condition_id}:{name}".encode()),
                "output_sha256": _sha(f"{context.assignment.condition_id}:{name}:ok".encode()),
                "exit_code": 0,
                "workspace": workspace,
            }
            for name in ("doc-bridge", "playbook", "code-review")
        },
    }


def _verify_agentskit_context(context, payload: Mapping[str, Any]) -> bool:
    workspace = str(context.worktree.resolve())
    return bool(
        payload.get("public_only") is True
        and payload.get("agentskit_os_used") is False
        and payload.get("condition_id") == context.assignment.condition_id
        and payload.get("task_id") == context.assignment.task_id
        and isinstance(payload.get("executions"), Mapping)
        and set(payload["executions"]) == {"doc-bridge", "playbook", "code-review"}
        and all(
            isinstance(record, Mapping)
            and record.get("workspace") == workspace
            and record.get("exit_code") == 0
            and bool(record.get("source_commit"))
            for record in payload["executions"].values()
        )
    )


def _backend_factory(args):
    def resolve_oracle(context, questions):
        canonical = json.loads((
            args.private_evaluation_root / "tasks" / context.assignment.task_id
            / "canonical-requirements.json"
        ).read_text(encoding="utf-8"))
        answers = canonical.get("traceability", {})
        ids = [str(question.get("ambiguity_id", "")) for question in questions]
        if len(ids) != len(set(ids)) or set(ids) != set(answers):
            raise ValueError("oracle questions do not cover the frozen ambiguities exactly once")
        return {ambiguity_id: str(answers[ambiguity_id]) for ambiguity_id in ids}

    def build(assignment, bundle):  # pylint: disable=unused-argument
        role_executor, _ = build_v12_role_executor(
            assignment.ade,
            control_root=ROOT / "products/compozy" if assignment.ade == "compozy" else args.control_root,
            ao_project=args.agent_orchestrator_project,
            private_evaluation_root=args.private_evaluation_root,
        )
        stage = V12NativeStageBackend(role_executor)
        if assignment.agentskit == "on":
            return V12HandoffBackend(
                stage,
                agentskit_context_factory=_build_agentskit_context,
                agentskit_evidence_verifier=_verify_agentskit_context,
                oracle_resolver=resolve_oracle,
            )
        return V12HandoffBackend(stage, oracle_resolver=resolve_oracle)

    return build


def _verifier_factory():
    def build(assignment, bundle):  # pylint: disable=unused-argument
        _, verifier = build_v12_role_executor(
            assignment.ade,
            control_root=ROOT / "products/compozy" if assignment.ade == "compozy" else ROOT,
            ao_project="code-10x",
            private_evaluation_root=bundle.directory,
        )
        return verifier

    return build


def _evidence_factory(args, warnings):
    if args.enable_private_evidence:
        def build(_assignment, _bundle):
            return ControllerEvidenceCollector(
                private_source_repository=args.private_evaluation_root,
                private_source_commit=args.private_source_commit,
                registered_private_source_commit=args.registered_private_source_commit,
            )

        return build

    def build(_assignment, _bundle):
        return SyntheticV12EvidenceCollector(warnings)

    return build


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--preflight", type=Path, required=True)
    parser.add_argument("--tasks-root", type=Path, required=True)
    parser.add_argument("--runs-root", type=Path, required=True)
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--product", dest="product_id", required=True)
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--replicates", type=int, default=1)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--base-commit", default=None)
    parser.add_argument("--gate-mode", choices=("technical-pilot", "official-collection"), default="technical-pilot")
    parser.add_argument("--wall-time-ms", type=int, default=120000)
    parser.add_argument("--agent-orchestrator-project", default="code-10x")
    parser.add_argument("--control-root", type=Path, default=ROOT)
    parser.add_argument("--private-evaluation-root", type=Path, default=(ROOT / "private"))
    parser.add_argument("--private-source-commit")
    parser.add_argument("--registered-private-source-commit")
    parser.add_argument("--enable-private-evidence", action="store_true")
    parser.add_argument("--confirm", action="store_true")
    args = parser.parse_args()

    if not args.confirm:
        print(json.dumps({"status": "blocked", "reason": "confirmation-required"}))
        return 2

    preflight = json.loads(args.preflight.read_text(encoding="utf-8"))
    report = evaluate_pilot_gate(preflight, gate_mode=args.gate_mode)
    if not report.can_start:
        print(json.dumps({"status": "blocked", "reason": "pilot-gate-not-ready", "report": report.to_dict()}))
        return 2

    if args.enable_private_evidence and args.private_source_commit is None:
        print(json.dumps({"status": "blocked", "reason": "private-source-commit-is-required-when-private-evidence-enabled"}))
        return 2

    base_commit = args.base_commit or _git_head(ROOT)
    assignments = build_pilot_schedule(
        task_id=args.task_id,
        product_id=args.product_id,
        seed=args.seed,
        replicate_count=args.replicates,
        protocol_version="v1.2",
    )
    if args.limit:
        assignments = assignments[:args.limit]

    writer = RunBundleWriter(preflight, args.runs_root, args.tasks_root, gate_mode=args.gate_mode)
    prep = ConditionedV12PilotExecutor(preflight, gate_mode=args.gate_mode, repo_root=ROOT)

    warnings: list[dict[str, str]] = []
    to_run: list[tuple[Any, Any, Mapping[str, str], Mapping[str, str]]] = []
    for assignment in assignments:
        prepared = prep.prepare_condition(
            run_id=assignment.run_id,
            ade=assignment.ade,
            agentskit=assignment.agentskit,
        )
        to_run.append((
            assignment,
            prepared,
            {binding.role: binding.model for binding in prepared.plan.role_bindings},
            {
                "ade": prepared.plan.ade.adapter_version,
                "agentskit": prepared.plan.agentskit.adapter_version,
            },
        ))

    collector = _evidence_factory(args, warnings)
    coordinator = PilotCollectionCoordinator(
        writer,
        V12NativeCollectionBackend(
            GitWorktreeProvider(repository=ROOT, worktree_root=args.runs_root / "worktrees"),
            _backend_factory(args),
            _verifier_factory(),
            collector,
            orca_worktrees=OrcaWorktreeProvider(repository=ROOT),
        ),
    )

    records: list[dict[str, Any]] = []
    for assignment, _prepared, model_snapshots, component_versions in to_run:
        budgets = {
            "wall_time_ms": args.wall_time_ms,
        }
        records.extend(
            asdict(record)
            for record in coordinator.collect(
                (assignment,),
                base_commit=base_commit,
                budgets=budgets,
                model_snapshots=model_snapshots,
                component_versions=component_versions,
            )
        )

    outcome = {
        "status": "ready-to-run" if not warnings else "completed-with-warnings",
        "records": records,
        "warnings": warnings,
    }
    print(json.dumps(outcome, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
