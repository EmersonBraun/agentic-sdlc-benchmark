"""macOS process boundary preventing measured agents from reading private evaluation."""

from __future__ import annotations

from pathlib import Path
from typing import Sequence


def sandbox_argv(argv: Sequence[str], denied_root: Path) -> tuple[str, ...]:
    root = denied_root.resolve()
    if denied_root.is_symlink() or not root.is_dir():
        raise RuntimeError("private evaluation deny root is invalid")
    escaped = str(root).replace("\\", "\\\\").replace('"', '\\"')
    profile = f'(version 1)(allow default)(deny file-read* (subpath "{escaped}"))'
    return ("/usr/bin/sandbox-exec", "-p", profile, *tuple(argv))
