#!/usr/bin/env python3
"""Materialize and build the pinned public AgentsKit component runtimes."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path


COMPONENTS = {
    "doc-bridge": ("https://github.com/AgentsKit-io/doc-bridge", "9a03016932b9e3024604712183152025c0577fe4"),
    "agents-playbook": ("https://github.com/AgentsKit-io/agents-playbook", "0818d860655c2d367f4d8b8c281c9b73ec5adad2"),
    "code-review-cli": ("https://github.com/AgentsKit-io/code-review-cli", "467cfa570a6b5f1076098b3c76be4e812562f23e"),
}


def _run(*args: str, cwd: Path | None = None) -> None:
    subprocess.run(args, cwd=cwd, check=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = args.output.resolve()
    if root.exists():
        raise SystemExit(f"Refusing to overwrite existing runtime root: {root}")
    root.mkdir(parents=True)

    for name, (repository, commit) in COMPONENTS.items():
        target = root / name
        _run("git", "clone", "--quiet", repository, str(target))
        _run("git", "checkout", "--quiet", commit, cwd=target)

    _run("pnpm", "install", "--frozen-lockfile", "--ignore-scripts", cwd=root / "doc-bridge")
    _run("pnpm", "build", cwd=root / "doc-bridge")
    _run("pnpm", "install", "--frozen-lockfile", "--ignore-scripts", cwd=root / "agents-playbook")
    _run("pnpm", "build:bundle", cwd=root / "agents-playbook")
    _run("pnpm", "test:playbook-package", cwd=root / "agents-playbook")
    _run("npm", "ci", "--ignore-scripts", cwd=root / "code-review-cli")
    _run("npm", "run", "build", cwd=root / "code-review-cli")

    print(json.dumps({"status": "ready", "root": str(root), "components": COMPONENTS}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
