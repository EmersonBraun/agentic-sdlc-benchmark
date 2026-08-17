"""Fail-closed creation of versioned benchmark run bundles."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from .ledger import Ledger
from .pilot_executor import ConditionedPilotExecutor, PreparedCondition


_COMMIT = re.compile(r"^[a-f0-9]{40}$")


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

    def __init__(self, preflight: Mapping[str, Any], output_root: Path) -> None:
        self._preflight = dict(preflight)
        self._output_root = output_root

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

        prepared = ConditionedPilotExecutor(self._preflight).prepare_condition(
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

        directory = (self._output_root / run_id).resolve()
        root = self._output_root.resolve()
        if root not in directory.parents:
            raise RunBundleError("run directory escapes output root")
        if directory.exists():
            raise RunBundleError(f"Run bundle already exists: {run_id}")

        manifest = {
            "schema_version": "1.1",
            "protocol_version": prepared.plan.protocol_version,
            "run_id": run_id,
            "task_id": task_id,
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
