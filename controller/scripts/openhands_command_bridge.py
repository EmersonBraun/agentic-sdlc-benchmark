#!/usr/bin/env python3
"""Execute one argv command through OpenHands LocalWorkspace."""

from __future__ import annotations

import argparse
import json
import shlex

from openhands.sdk import LocalWorkspace


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command_json")
    args = parser.parse_args()
    command = json.loads(args.command_json)
    if not isinstance(command, list) or not command or any(not isinstance(part, str) or not part for part in command):
        raise ValueError("command_json must encode non-empty argv strings")
    workspace = LocalWorkspace(working_dir="/workspace")
    with workspace:
        completed = workspace.execute_command(shlex.join(command), cwd="/workspace", timeout=3600)
    print(json.dumps({
        "schema_version": "openhands-command-result-v1.1",
        "returncode": completed.exit_code,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
