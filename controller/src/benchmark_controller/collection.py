"""Fail-closed collection coordinator for prepared pilot assignments."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Protocol

from .matrix import MatrixAssignment
from .run_bundles import PreparedRunBundle, RunBundleWriter


TERMINAL_STATES = frozenset({
    "MERGED",
    "FAILED",
    "TIMEOUT",
    "BUDGET_EXCEEDED",
    "HUMAN_REQUIRED",
    "INFRASTRUCTURE_FAILURE",
    "INVALID_MEASUREMENT",
})


@dataclass(frozen=True)
class ExecutionOutcome:
    """The only result a live ADE/harness backend may return to the controller."""

    terminal_state: str
    artifacts: tuple[dict[str, str], ...] = ()
    failure: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        if self.terminal_state not in TERMINAL_STATES:
            raise ValueError(f"Invalid execution terminal state: {self.terminal_state!r}")


class CollectionBackend(Protocol):
    """Adapter seam for an actual ADE × harness × AgentsKit implementation."""

    def execute(self, assignment: MatrixAssignment, bundle: PreparedRunBundle) -> ExecutionOutcome:
        """Execute one assigned task and return only redacted, normalized outcome metadata."""


@dataclass(frozen=True)
class CollectionRecord:
    run_id: str
    condition_id: str
    terminal_state: str
    failure: dict[str, Any] | None


class PilotCollectionCoordinator:
    """Prepare, dispatch, and finalize a seeded schedule without substitutions."""

    def __init__(self, writer: RunBundleWriter, backend: CollectionBackend) -> None:
        self.writer = writer
        self.backend = backend

    def collect(self, assignments: Iterable[MatrixAssignment], **run_context: Any) -> tuple[CollectionRecord, ...]:
        records: list[CollectionRecord] = []
        for assignment in assignments:
            bundle = self.writer.create(
                run_id=assignment.run_id,
                task_id=assignment.task_id,
                product_id=assignment.product_id,
                ade=assignment.ade,
                harness=assignment.harness,
                agentskit=assignment.agentskit,
                replicate=assignment.replicate,
                randomization_seed=assignment.randomization_seed,
                **run_context,
            )
            bundle.ledger.record(
                stage_id="intake",
                actor="controller",
                event_type="run.started",
                time_category="orchestration_overhead",
                duration_ms=0,
                status="started",
                payload={"condition_id": assignment.condition_id, "schedule_order": assignment.order},
                tool="benchmark-controller",
            )
            try:
                outcome = self.backend.execute(assignment, bundle)
                if not isinstance(outcome, ExecutionOutcome):
                    raise TypeError("collection backend must return ExecutionOutcome")
            except Exception as exc:
                outcome = ExecutionOutcome(
                    terminal_state="INFRASTRUCTURE_FAILURE",
                    failure={"error_type": type(exc).__name__},
                )
            final_manifest = self.writer.finalize(
                bundle,
                terminal_state=outcome.terminal_state,
                artifacts=list(outcome.artifacts),
                failure=outcome.failure,
            )
            records.append(
                CollectionRecord(
                    run_id=assignment.run_id,
                    condition_id=assignment.condition_id,
                    terminal_state=str(final_manifest["terminal_state"]),
                    failure=outcome.failure,
                )
            )
        return tuple(records)
