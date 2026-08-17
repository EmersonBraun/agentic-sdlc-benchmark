"""Validation helpers for immutable benchmark identifiers."""

from __future__ import annotations

import re


_ID_PATTERNS = {
    "event": re.compile(r"^evt_[A-Za-z0-9_-]+$"),
    "run": re.compile(r"^run_[A-Za-z0-9_-]+$"),
    "task": re.compile(r"^(pilot|main|holdout)_[A-Za-z0-9_-]+$"),
}


def validate_id(value: str, kind: str) -> str:
    """Return *value* when it matches the immutable identifier contract."""

    try:
        pattern = _ID_PATTERNS[kind]
    except KeyError as exc:
        raise ValueError(f"Unknown identifier kind: {kind}") from exc

    if not isinstance(value, str) or pattern.fullmatch(value) is None:
        raise ValueError(f"Invalid {kind} identifier: {value!r}")
    return value
