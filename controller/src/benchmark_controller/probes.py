"""Side-effect-free executable probes for adapter readiness."""

from __future__ import annotations

import hashlib
import os
import subprocess
from dataclasses import asdict, dataclass
from typing import Mapping, Sequence


@dataclass(frozen=True)
class ProbeSpec:
    probe_id: str
    command: tuple[str, ...]
    expected_output: tuple[str, ...] = ()


@dataclass(frozen=True)
class ProbeResult:
    probe_id: str
    command: tuple[str, ...]
    returncode: int
    passed: bool
    timed_out: bool
    output_sha256: str
    output_preview: str

    def to_dict(self) -> dict[str, object]:
        result = asdict(self)
        result["command"] = list(self.command)
        return result


def run_probe(
    spec: ProbeSpec,
    *,
    cwd: str | None = None,
    env: Mapping[str, str] | None = None,
    timeout_seconds: float = 10,
) -> ProbeResult:
    """Run an argv-only probe and hash, rather than publish, its output."""

    if not spec.probe_id or not spec.command or any(not part for part in spec.command):
        raise ValueError("probe_id and command parts must be non-empty")
    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be positive")

    process_env = os.environ.copy()
    if env:
        process_env.update(env)
    try:
        completed = subprocess.run(
            list(spec.command),
            cwd=cwd,
            env=process_env,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
        output = f"{completed.stdout}{completed.stderr}"
        timed_out = False
        returncode = completed.returncode
    except subprocess.TimeoutExpired as exc:
        output = f"{exc.stdout or ''}{exc.stderr or ''}"
        timed_out = True
        returncode = 124
    except OSError as exc:
        output = f"{type(exc).__name__}: {exc}"
        timed_out = False
        returncode = 127

    output_bytes = output.encode("utf-8", errors="replace")
    passed = not timed_out and returncode == 0 and all(
        expected in output for expected in spec.expected_output
    )
    return ProbeResult(
        probe_id=spec.probe_id,
        command=spec.command,
        returncode=returncode,
        passed=passed,
        timed_out=timed_out,
        output_sha256=hashlib.sha256(output_bytes).hexdigest(),
        output_preview=output[:500],
    )


def assert_probe_suite(results: Sequence[ProbeResult]) -> None:
    """Fail closed if any required probe fails."""

    failures = [result.probe_id for result in results if not result.passed]
    if failures:
        raise RuntimeError(f"Adapter probes failed: {', '.join(failures)}")
