"""Fail-closed creation of versioned benchmark run bundles."""

from __future__ import annotations

import hashlib
import json
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from .ledger import Ledger
from .pilot import GateMode
from .pilot_executor import ConditionedPilotExecutor, PreparedCondition


_COMMIT = re.compile(r"^[a-f0-9]{40}$")
_ARTIFACT_SHA256 = re.compile(r"^[a-f0-9]{64}$")
_TERMINAL_STATES = {
    "MERGED",
    "FAILED",
    "TIMEOUT",
    "BUDGET_EXCEEDED",
    "HUMAN_REQUIRED",
    "INFRASTRUCTURE_FAILURE",
    "INVALID_MEASUREMENT",
}


class RunBundleError(RuntimeError):
    """Raised when a run bundle cannot be created safely."""


@dataclass(frozen=True)
class PreparedRunBundle:
    """A newly created bundle with an empty append-only ledger."""

    directory: Path
    manifest: dict[str, Any]
    ledger: Ledger
    condition: PreparedCondition


class RunBundleWriter:
    """Create a run bundle only after all pilot gates and parity checks pass."""

    def __init__(
        self,
        preflight: Mapping[str, Any],
        output_root: Path,
        tasks_root: Path | None = None,
        *,
        gate_mode: GateMode = "official-collection",
    ) -> None:
        self._preflight = dict(preflight)
        self._output_root = output_root
        self._tasks_root = tasks_root
        self._gate_mode = gate_mode

    def create(
        self,
        *,
        run_id: str,
        task_id: str,
        product_id: str,
        ade: str,
        harness: str,
        agentskit: str,
        replicate: int,
        randomization_seed: int,
        base_commit: str,
        model_snapshots: Mapping[str, str],
        component_versions: Mapping[str, str],
        environment: Mapping[str, Any] | None = None,
        budgets: Mapping[str, Any] | None = None,
    ) -> PreparedRunBundle:
        """Prepare the immutable public bundle and its empty ledger.

        Gate evaluation happens before the output directory is touched. A
        blocked or invalid preparation therefore leaves no partial run behind.
        """

        prepared = ConditionedPilotExecutor(self._preflight, gate_mode=self._gate_mode).prepare_condition(
            run_id=run_id,
            ade=ade,
            harness=harness,
            agentskit=agentskit,
        )
        if not isinstance(task_id, str) or not task_id.startswith(("pilot_", "main_", "holdout_")):
            raise RunBundleError(f"Invalid task identifier: {task_id!r}")
        if product_id not in {"greenfield", "umami"}:
            raise RunBundleError(f"Unsupported product: {product_id!r}")
        if not isinstance(replicate, int) or isinstance(replicate, bool) or replicate < 1:
            raise RunBundleError("replicate must be a positive integer")
        if not isinstance(randomization_seed, int) or isinstance(randomization_seed, bool) or randomization_seed < 0:
            raise RunBundleError("randomization_seed must be a non-negative integer")
        if not _COMMIT.fullmatch(base_commit):
            raise RunBundleError("base_commit must be a 40-character lowercase SHA-1")

        if self._tasks_root is None:
            raise RunBundleError("tasks_root is required for task-manifest binding")
        task_manifest_path = self._tasks_root / f"{task_id}.manifest.json"
        if not task_manifest_path.is_file():
            raise RunBundleError(f"Task manifest not found: {task_id}")
        try:
            task_manifest = json.loads(task_manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RunBundleError(f"Task manifest is unreadable: {task_id}") from exc
        if task_manifest.get("task_id") != task_id or task_manifest.get("product_id") != product_id:
            raise RunBundleError("Task manifest identity does not match the requested run")
        expected_phase = "pilot" if task_id.startswith("pilot_") else "main" if task_id.startswith("main_") else "holdout"
        if task_manifest.get("phase") != expected_phase:
            raise RunBundleError("Task manifest phase does not match the task identifier")
        task_manifest_sha256 = hashlib.sha256(task_manifest_path.read_bytes()).hexdigest()

        directory = (self._output_root / run_id).resolve()
        root = self._output_root.resolve()
        if root not in directory.parents:
            raise RunBundleError("run directory escapes output root")
        if directory.exists():
            raise RunBundleError(f"Run bundle already exists: {run_id}")

        manifest = {
            "schema_version": "1.1",
            "protocol_version": prepared.plan.protocol_version,
            "gate_mode": self._gate_mode,
            "analysis_eligible": self._gate_mode == "official-collection",
            "run_id": run_id,
            "task_id": task_id,
            "task_manifest_sha256": task_manifest_sha256,
            "product_id": product_id,
            "condition_id": f"{ade}__{harness}__{agentskit}",
            "replicate": replicate,
            "randomization_seed": randomization_seed,
            "base_commit": base_commit,
            "model_snapshots": dict(model_snapshots),
            "component_versions": dict(component_versions),
            "environment": dict(environment or {}),
            "budgets": dict(budgets or {}),
            "terminal_state": "NOT_APPLICABLE",
            "artifacts": [],
        }
        directory.mkdir(parents=True)
        (directory / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        (directory / "artifact-index.json").write_text(
            json.dumps({"run_id": run_id, "artifacts": []}, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        (directory / "evaluation-refs.json").write_text(
            json.dumps({"run_id": run_id, "references": []}, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        ledger_path = directory / "ledger.jsonl"
        ledger = Ledger(ledger_path, run_id=run_id, task_id=task_id)
        ledger_path.touch(exist_ok=True)
        return PreparedRunBundle(directory=directory, manifest=manifest, ledger=ledger, condition=prepared)

    def finalize(
        self,
        bundle: PreparedRunBundle,
        *,
        terminal_state: str,
        artifacts: list[dict[str, str]] | None = None,
        failure: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Close one prepared bundle and record its terminal state exactly once."""

        if terminal_state not in _TERMINAL_STATES:
            raise RunBundleError(f"Invalid terminal state: {terminal_state!r}")
        current = json.loads((bundle.directory / "manifest.json").read_text(encoding="utf-8"))
        if current.get("terminal_state") != "NOT_APPLICABLE":
            raise RunBundleError("Run bundle is already finalized")
        normalized_artifacts = _validate_artifacts(artifacts or [])
        if failure is not None and not isinstance(failure, dict):
            raise RunBundleError("failure must be an object or null")
        final_manifest = {
            **current,
            "terminal_state": terminal_state,
            "artifacts": normalized_artifacts,
            "failure": dict(failure) if failure else None,
        }
        _atomic_json_write(bundle.directory / "manifest.json", final_manifest)
        _atomic_json_write(
            bundle.directory / "artifact-index.json",
            {"run_id": current["run_id"], "artifacts": normalized_artifacts},
        )
        bundle.ledger.record(
            stage_id="documentation",
            actor="controller",
            event_type="run.terminal",
            time_category="instrumentation_overhead",
            duration_ms=0,
            status="completed" if terminal_state == "MERGED" else "failed",
            payload={
                "terminal_state": terminal_state,
                "artifact_count": len(normalized_artifacts),
                "failure_present": bool(failure),
            },
            tool="benchmark-controller",
        )
        return final_manifest


def _validate_artifacts(artifacts: list[dict[str, str]]) -> list[dict[str, str]]:
    normalized: list[dict[str, str]] = []
    for artifact in artifacts:
        if not isinstance(artifact, dict):
            raise RunBundleError("artifact must be an object")
        path = artifact.get("path")
        digest = artifact.get("sha256")
        visibility = artifact.get("visibility")
        if not isinstance(path, str) or not path or Path(path).is_absolute() or ".." in Path(path).parts:
            raise RunBundleError("artifact path must be a relative non-escaping path")
        if not isinstance(digest, str) or not _ARTIFACT_SHA256.fullmatch(digest):
            raise RunBundleError("artifact sha256 must be a lowercase SHA-256")
        if visibility not in {"public", "private", "redacted"}:
            raise RunBundleError("artifact visibility is invalid")
        normalized.append({"path": path, "sha256": digest, "visibility": visibility})
    return normalized


def _atomic_json_write(path: Path, value: dict[str, Any]) -> None:
    """Replace a JSON file atomically within its existing directory."""

    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", delete=False
    ) as stream:
        temporary = Path(stream.name)
        stream.write(json.dumps(value, indent=2, sort_keys=True) + "\n")
    temporary.replace(path)
