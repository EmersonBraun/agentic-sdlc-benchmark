"""Controller-owned evidence and blind snapshot boundaries for v1.2."""

from __future__ import annotations

import hashlib
import io
import json
import os
import re
import shutil
import stat
import subprocess
import tarfile
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Iterator, Mapping

SHA1 = re.compile(r"^[a-f0-9]{40}$")
SHA256 = re.compile(r"^[a-f0-9]{64}$")
EXCLUDED_NAMES = {"AGENTS.md", "CLAUDE.md"}
EXCLUDED_PARTS = {".agents", ".codex", "runtime-control"}
EXCLUDED_EXACT = {PurePosixPath(".github/copilot-instructions.md")}
REQUIRED_EXTERNAL_GATES = {"build", "typecheck", "ci", "essential-hidden-tests", "ledger"}
COMMAND_KINDS = {"build", "typecheck", "ci", "hidden-tests", "ledger-validation"}


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@dataclass(frozen=True)
class ControllerEvidenceAttestation:
    path: Path
    document: Mapping[str, Any]
    sha256: str

    @classmethod
    def load(
        cls, path: Path, *, task_id: str, task_manifest_sha256: str,
        product_commit: str, ledger_prefix: bytes,
    ) -> "ControllerEvidenceAttestation":
        raw = path.read_bytes()
        value = json.loads(raw)
        if not isinstance(value, Mapping):
            raise ValueError("controller evidence must be an object")
        cls._validate(
            value, task_id=task_id, task_manifest_sha256=task_manifest_sha256,
            product_commit=product_commit, ledger_prefix=ledger_prefix,
        )
        return cls(path.resolve(), dict(value), _sha(raw))

    @staticmethod
    def _validate(
        value: Mapping[str, Any], *, task_id: str, task_manifest_sha256: str,
        product_commit: str, ledger_prefix: bytes,
    ) -> None:
        expected = {
            "schema_version", "protocol_version", "task_id", "task_manifest_sha256",
            "product_commit", "private_source_commit", "hard_gates",
            "hidden_test_summary", "ledger_prefix_sha256", "command_evidence",
        }
        if set(value) != expected or not all((
            value.get("schema_version") == "controller-evidence-attestation-v1.2",
            value.get("protocol_version") == "v1.2",
            value.get("task_id") == task_id,
            value.get("task_manifest_sha256") == task_manifest_sha256,
            value.get("product_commit") == product_commit,
            isinstance(value.get("private_source_commit"), str),
            bool(SHA1.fullmatch(str(value.get("private_source_commit", "")))),
            value.get("ledger_prefix_sha256") == _sha(ledger_prefix),
        )):
            raise ValueError("controller evidence identity mismatch")
        gates = value.get("hard_gates")
        if not isinstance(gates, Mapping) or set(gates) != REQUIRED_EXTERNAL_GATES or not all(
            isinstance(item, bool) for item in gates.values()
        ):
            raise ValueError("controller hard gates are incomplete")
        hidden = value.get("hidden_test_summary")
        hidden_keys = {
            "total", "passed", "failed", "critical_mutants_killed",
            "noncritical_mutant_kill_rate",
        }
        if not isinstance(hidden, Mapping) or set(hidden) != hidden_keys:
            raise ValueError("hidden-test summary is incomplete")
        total, passed, failed = hidden.get("total"), hidden.get("passed"), hidden.get("failed")
        if not all(isinstance(item, int) and not isinstance(item, bool) for item in (total, passed, failed)):
            raise ValueError("hidden-test counts are invalid")
        if total < 1 or passed < 0 or failed < 0 or passed + failed != total:
            raise ValueError("hidden-test counts do not reconcile")
        rate = hidden.get("noncritical_mutant_kill_rate")
        if not isinstance(rate, (int, float)) or isinstance(rate, bool) or not 0 <= rate <= 1:
            raise ValueError("mutant kill rate is invalid")
        hidden_pass = (
            failed == 0 and hidden.get("critical_mutants_killed") is True and rate >= 0.8
        )
        if gates["essential-hidden-tests"] is not hidden_pass:
            raise ValueError("hidden-test gate contradicts bounded evidence")
        commands = value.get("command_evidence")
        if (
            not isinstance(commands, list)
            or len(commands) != len(COMMAND_KINDS)
            or {item.get("kind") for item in commands if isinstance(item, Mapping)} != COMMAND_KINDS
        ):
            raise ValueError("controller command evidence is incomplete")
        for item in commands:
            if not isinstance(item, Mapping) or set(item) != {
                "kind", "command_sha256", "output_sha256", "exit_code",
            } or not all((
                item.get("kind") in COMMAND_KINDS,
                isinstance(item.get("command_sha256"), str),
                bool(SHA256.fullmatch(str(item.get("command_sha256", "")))),
                isinstance(item.get("output_sha256"), str),
                bool(SHA256.fullmatch(str(item.get("output_sha256", "")))),
                isinstance(item.get("exit_code"), int),
                not isinstance(item.get("exit_code"), bool),
            )):
                raise ValueError("controller command evidence record is invalid")
        by_kind = {item["kind"]: item for item in commands}
        for gate, kind in {
            "build": "build", "typecheck": "typecheck", "ci": "ci",
            "essential-hidden-tests": "hidden-tests", "ledger": "ledger-validation",
        }.items():
            if gates[gate] is not (by_kind[kind]["exit_code"] == 0):
                raise ValueError(f"{gate} gate contradicts command evidence")

    def public_summary(self) -> dict[str, Any]:
        hidden = self.document["hidden_test_summary"]
        return {
            "attestation_sha256": self.sha256,
            "hard_gates": dict(self.document["hard_gates"]),
            "hidden_test_summary": {
                "total": hidden["total"], "passed": hidden["passed"],
                "failed": hidden["failed"],
                "critical_mutants_killed": hidden["critical_mutants_killed"],
                "noncritical_mutant_kill_rate": hidden["noncritical_mutant_kill_rate"],
            },
        }


@dataclass(frozen=True)
class BlindSnapshot:
    path: Path
    product_commit: str
    tree_sha256: str
    excluded_paths: tuple[str, ...]


@contextmanager
def blind_snapshot(worktree: Path, *, expected_commit: str) -> Iterator[BlindSnapshot]:
    """Yield an opaque committed snapshot with all instruction surfaces removed."""

    root = worktree.resolve()
    if not SHA1.fullmatch(expected_commit):
        raise ValueError("expected commit is invalid")
    head = _git(root, "rev-parse", "HEAD")
    status_output = _git(root, "status", "--porcelain", "--untracked-files=all")
    if head != expected_commit or status_output:
        raise RuntimeError("evaluation source is not the expected clean commit")
    archive = subprocess.run(
        ("git", "-C", str(root), "archive", "--format=tar", expected_commit),
        capture_output=True, check=False,
    )
    if archive.returncode != 0:
        raise RuntimeError("evaluation snapshot archive failed")
    temporary = Path(tempfile.mkdtemp(prefix="v12-blind-"))
    excluded: list[str] = []
    digest = hashlib.sha256()
    try:
        with tarfile.open(fileobj=io.BytesIO(archive.stdout), mode="r:") as stream:
            for member in stream.getmembers():
                relative = PurePosixPath(member.name)
                if relative.is_absolute() or ".." in relative.parts:
                    raise RuntimeError("evaluation archive contains an unsafe path")
                if _excluded(relative):
                    excluded.append(relative.as_posix())
                    continue
                if member.isdir():
                    (temporary / relative).mkdir(parents=True, exist_ok=True)
                    continue
                if not member.isfile():
                    raise RuntimeError("evaluation archive contains a non-file entry")
                source = stream.extractfile(member)
                if source is None:
                    raise RuntimeError("evaluation archive member is unreadable")
                payload = source.read()
                target = temporary / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(payload)
                target.chmod(stat.S_IMODE(member.mode) & 0o755)
                digest.update(relative.as_posix().encode())
                digest.update(payload)
        yield BlindSnapshot(temporary, expected_commit, digest.hexdigest(), tuple(sorted(excluded)))
    finally:
        shutil.rmtree(temporary, ignore_errors=False)


def _excluded(path: PurePosixPath) -> bool:
    return (
        path.name in EXCLUDED_NAMES
        or any(part in EXCLUDED_PARTS for part in path.parts)
        or path in EXCLUDED_EXACT
    )


def _git(root: Path, *args: str) -> str:
    completed = subprocess.run(
        ("git", "-C", str(root), *args), capture_output=True, text=True, check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError("evaluation git identity check failed")
    return completed.stdout.strip()
