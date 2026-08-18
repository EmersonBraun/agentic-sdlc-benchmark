#!/usr/bin/env python3
"""Execute the provider-free OpenHands workspace contract inside the pinned container."""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
from pathlib import Path

from openhands.sdk import LocalWorkspace

EXPECTED = {
    "openhands-sdk": "1.42.1",
    "openhands-tools": "1.42.1",
    "openhands-workspace": "1.42.1",
    "openhands-agent-server": "1.42.1",
}
MARKER = "OPENHANDS_WORKSPACE_READY"
IGNORED = {".git", ".next", ".DS_Store", "node_modules"}


def sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def tree_sha256(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        if any(part in IGNORED for part in relative.parts):
            continue
        digest.update(str(relative).encode())
        if path.is_symlink():
            digest.update(b"symlink\0" + str(path.readlink()).encode())
        elif path.is_file():
            digest.update(b"file\0" + path.read_bytes())
        else:
            digest.update(b"dir\0")
    return digest.hexdigest()


def main() -> int:
    versions = {name: importlib.metadata.version(name) for name in EXPECTED}
    workspace = LocalWorkspace(working_dir="/workspace")
    with workspace:
        read = workspace.execute_command(
            "python -c \"print('OPENHANDS_WORKSPACE_READY')\"", cwd="/workspace", timeout=30
        )
        denied = workspace.execute_command(
            "python -c \"from pathlib import Path; Path('/workspace/.forbidden-write').write_text('x')\"",
            cwd="/workspace",
            timeout=30,
        )
    result = {
        "schema_version": "openhands-native-probe-v1.1",
        "versions": versions,
        "versions_exact": versions == EXPECTED,
        "workspace_type": type(workspace).__name__,
        "read_exit_code": read.exit_code,
        "read_marker_observed": read.stdout.strip() == MARKER,
        "read_stdout_sha256": sha256(read.stdout),
        "write_exit_code": denied.exit_code,
        "write_denied": denied.exit_code != 0,
        "write_stderr_sha256": sha256(denied.stderr),
        "workspace_tree_sha256": tree_sha256(Path("/workspace")),
        "raw_content_in_result": False,
    }
    print(json.dumps(result, sort_keys=True))
    return 0 if all((result["versions_exact"], result["read_marker_observed"], result["write_denied"])) else 1


if __name__ == "__main__":
    raise SystemExit(main())
