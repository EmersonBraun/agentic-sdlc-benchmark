"""Deterministic pilot scheduling for the frozen 18-condition matrix."""

from __future__ import annotations

import random
import re
from dataclasses import asdict, dataclass
from typing import Any, Mapping

from .conditions import EXPECTED_ADE, EXPECTED_AGENTSKIT, EXPECTED_HARNESSES

_TASK_ID = re.compile(r"^(pilot|main|holdout)_[A-Za-z0-9_-]+$")


@dataclass(frozen=True)
class MatrixAssignment:
    order: int
    run_id: str
    task_id: str
    product_id: str
    condition_id: str
    ade: str
    harness: str
    agentskit: str
    replicate: int
    randomization_seed: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_pilot_schedule(
    *,
    task_id: str,
    product_id: str,
    seed: int,
    replicate_count: int = 1,
) -> tuple[MatrixAssignment, ...]:
    """Return a seeded schedule without invoking an ADE, harness, or model."""

    if not _TASK_ID.fullmatch(task_id) or not task_id.startswith("pilot_"):
        raise ValueError("pilot schedule requires a pilot task identifier")
    if product_id not in {"greenfield", "umami"}:
        raise ValueError(f"Unsupported product: {product_id!r}")
    if not isinstance(seed, int) or isinstance(seed, bool) or seed < 0:
        raise ValueError("seed must be a non-negative integer")
    if not isinstance(replicate_count, int) or isinstance(replicate_count, bool) or replicate_count < 1:
        raise ValueError("replicate_count must be a positive integer")

    conditions = [
        (ade, harness, agentskit)
        for ade in sorted(EXPECTED_ADE)
        for harness in sorted(EXPECTED_HARNESSES)
        for agentskit in sorted(EXPECTED_AGENTSKIT)
    ]
    random.Random(seed).shuffle(conditions)
    assignments: list[MatrixAssignment] = []
    for order, (ade, harness, agentskit) in enumerate(conditions, 1):
        condition_id = f"{ade}__{harness}__{agentskit}"
        for replicate in range(1, replicate_count + 1):
            assignments.append(
                MatrixAssignment(
                    order=order,
                    run_id=f"run_v11_pilot_{ade}_{harness}_{agentskit}_r{replicate:02d}",
                    task_id=task_id,
                    product_id=product_id,
                    condition_id=condition_id,
                    ade=ade,
                    harness=harness,
                    agentskit=agentskit,
                    replicate=replicate,
                    randomization_seed=seed + order * 100 + replicate,
                )
            )
    return tuple(assignments)
