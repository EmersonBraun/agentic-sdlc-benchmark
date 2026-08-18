"""Validation helpers for the Compozy to Grok CLI ACP binding."""

from __future__ import annotations

import hashlib
import shlex
from pathlib import Path
from typing import Any, Mapping, Sequence

PROVIDER_ID = "grok-cli"
MODEL_ID = "grok-4.5"
REASONING_EFFORT = "low"


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def validate_provider_config(provider: Mapping[str, Any]) -> tuple[str, ...]:
    """Fail closed unless the effective provider uses the frozen native ACP command."""

    command = provider.get("command")
    if not isinstance(command, str) or not command.strip():
        raise ValueError("grok-cli provider command is missing")
    argv = tuple(shlex.split(command))
    if not argv or Path(argv[0]).name != "grok":
        raise ValueError("grok-cli provider must execute the Grok CLI")
    required = ("agent", "--model", MODEL_ID, "--reasoning-effort", REASONING_EFFORT, "stdio")
    if argv[1:] != required:
        raise ValueError("grok-cli provider command does not match the frozen ACP runtime")
    expected = {
        "auth_mode": "native_cli",
        "env_policy": "filtered",
        "home_policy": "operator",
    }
    for key, value in expected.items():
        if provider.get(key) != value:
            raise ValueError(f"grok-cli provider {key} must be {value}")
    if provider.get("credential_slots"):
        raise ValueError("grok-cli provider must not use Compozy-bound credentials")
    return argv


def summarize_events(events: Sequence[Mapping[str, Any]], sentinel: str) -> dict[str, Any]:
    event_types: dict[str, int] = {}
    agent_text_parts: list[str] = []
    providers: set[str] = set()
    done = False
    for event in events:
        event_type = str(event.get("type", "unknown"))
        event_types[event_type] = event_types.get(event_type, 0) + 1
        content = event.get("content")
        if isinstance(content, Mapping):
            text = content.get("text")
            if isinstance(text, str) and event_type == "agent_message":
                agent_text_parts.append(text)
            runtime = content.get("prompt_runtime")
            if (
                event_type in {"thought", "agent_message", "done"}
                and isinstance(runtime, Mapping)
                and isinstance(runtime.get("provider"), str)
            ):
                providers.add(str(runtime["provider"]))
        if event_type == "done":
            done = True
    return {
        "event_count": len(events),
        "event_types": dict(sorted(event_types.items())),
        "sentinel_observed": sentinel in "".join(agent_text_parts),
        "done_observed": done,
        "providers": sorted(providers),
    }
