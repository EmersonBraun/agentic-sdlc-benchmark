#!/usr/bin/env python3
"""Materialize public AgentsKit components and run bounded offline checks."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any


REPOSITORIES = {
    "doc-bridge": {
        "url": "https://github.com/AgentsKit-io/doc-bridge.git",
        "manager": "pnpm",
        "prepare": [("pnpm", "build"), ("pnpm", "typecheck")],
        "checks": [("pnpm", "test:readme-standard"), ("pnpm", "test:portable-skill")],
    },
    "playbook": {
        "url": "https://github.com/AgentsKit-io/agents-playbook.git",
        "manager": "pnpm",
        "prepare": [("pnpm", "exec", "fumadocs-mdx")],
        "checks": [("pnpm", "lint"), ("pnpm", "test:readme-standard"), ("pnpm", "test:playbook-package")],
    },
    "code-review": {
        "url": "https://github.com/AgentsKit-io/code-review-cli.git",
        "manager": "npm",
        "prepare": [("npm", "run", "typecheck")],
        "checks": [("npm", "run", "test:readme-standard")],
    },
}


def _run(command: tuple[str, ...], cwd: Path, *, timeout: int = 360, env: dict[str, str] | None = None) -> tuple[int, str]:
    result = subprocess.run(command, cwd=cwd, capture_output=True, text=True, timeout=timeout, env=env)
    return result.returncode, result.stdout + result.stderr


def _summary(raw: str) -> list[str]:
    return [
        line.strip()
        for line in raw.splitlines()
        if re.search(r"(passed|failed|tests|test files|error|success|pass)", line, re.I)
    ][-10:]


def _install(repo: str, path: Path, manager: str, environment: dict[str, str]) -> tuple[int, str]:
    if manager == "npm":
        command = ("npm", "ci", "--ignore-scripts", "--no-audit", "--no-fund")
    else:
        command = ("pnpm", "install", "--frozen-lockfile", "--ignore-scripts", "--prefer-offline", "--reporter", "append-only")
    return _run(command, path, timeout=360, env=environment)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--node-bin", default="")
    args = parser.parse_args()
    environment = os.environ.copy()
    if args.node_bin:
        environment["PATH"] = f"{args.node_bin}:{environment['PATH']}"

    result: dict[str, Any] = {
        "schema_version": "agentskit-external-attestation-v1.0",
        "protocol_version": "v1.0",
        "public_only": True,
        "agentskit_os_used": False,
        "provider_called": False,
        "agent_session_started": False,
        "repositories": {},
    }
    with tempfile.TemporaryDirectory(prefix="agentic-sdlc-public-agentskit-components-") as directory:
        root = Path(directory)
        for name, spec in REPOSITORIES.items():
            target = root / name
            clone_code, clone_output = _run(("git", "clone", "--depth", "1", "--no-tags", spec["url"], str(target)), root, timeout=180, env=environment)
            entry: dict[str, Any] = {"clone": "passed" if clone_code == 0 else "failed"}
            if clone_code != 0:
                entry["clone_summary"] = _summary(clone_output)
                result["repositories"][name] = entry
                continue
            revision = subprocess.run(("git", "rev-parse", "HEAD"), cwd=target, capture_output=True, text=True, check=True, env=environment).stdout.strip()
            install_code, install_output = _install(name, target, spec["manager"], environment)
            entry.update({"commit": revision, "install": "passed" if install_code == 0 else "failed"})
            if install_code != 0:
                entry["install_summary"] = _summary(install_output)
                result["repositories"][name] = entry
                continue
            entry["preparation"] = {}
            for command in spec["prepare"]:
                code, output = _run(command, target, timeout=360, env=environment)
                entry["preparation"][" ".join(command)] = {"returncode": code, "summary": _summary(output)}
            entry["offline_checks"] = {}
            for command in spec["checks"]:
                code, output = _run(command, target, timeout=360, env=environment)
                entry["offline_checks"][" ".join(command)] = {"returncode": code, "summary": _summary(output)}
            result["repositories"][name] = entry
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
