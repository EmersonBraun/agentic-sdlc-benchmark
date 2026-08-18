"""Redacted validation of Agent Orchestrator's persisted provider evidence."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any

REQUIRED_PROVIDER_EVENTS = frozenset(
    {"turn.started", "message.completed", "usage", "turn.completed"}
)
REQUIRED_PROVIDER_SEQUENCE = ("turn.started", "message.completed", "usage", "turn.completed")


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def read_provider_evidence(database: Path, session_id: str, expected_reply: str) -> dict[str, Any]:
    """Read only bounded metadata from AO's datastore; never return message content."""

    uri = f"file:{database}?mode=ro"
    with sqlite3.connect(uri, uri=True) as connection:
        conversation = connection.execute(
            "SELECT id FROM conversations WHERE session_id = ? ORDER BY updated_at DESC LIMIT 1",
            (session_id,),
        ).fetchone()
        if not conversation:
            return _empty_evidence()
        conversation_id = str(conversation[0])
        methods = [
            str(row[0])
            for row in connection.execute(
                "SELECT method FROM conversation_provider_events WHERE conversation_id = ? ORDER BY id",
                (conversation_id,),
            )
            if str(row[0]) in REQUIRED_PROVIDER_EVENTS
        ]
        messages = connection.execute(
            """
            SELECT m.text
            FROM conversations c
            JOIN conversation_messages m ON m.conversation_id = c.id
            WHERE c.session_id = ? AND m.role = 'assistant' AND m.streaming = 0
            ORDER BY m.sequence
            """,
            (session_id,),
        ).fetchall()
        usage = connection.execute(
            """
            SELECT COALESCE(MAX(c.usage_input_tokens), 0), COALESCE(MAX(c.usage_output_tokens), 0)
            FROM conversations c WHERE c.session_id = ?
            """,
            (session_id,),
        ).fetchone()

    assistant_text = str(messages[-1][0]).strip() if messages else ""
    return {
        "provider_event_sequence": methods,
        "required_provider_sequence_complete": tuple(methods) == REQUIRED_PROVIDER_SEQUENCE,
        "assistant_message_count": len(messages),
        "expected_reply_observed": assistant_text == expected_reply,
        "assistant_reply_sha256": sha256_text(assistant_text) if assistant_text else None,
        "input_tokens_observed": int(usage[0]) if usage else 0,
        "output_tokens_observed": int(usage[1]) if usage else 0,
        "raw_content_in_attestation": False,
    }


def _empty_evidence() -> dict[str, Any]:
    return {
        "provider_event_sequence": [],
        "required_provider_sequence_complete": False,
        "assistant_message_count": 0,
        "expected_reply_observed": False,
        "assistant_reply_sha256": None,
        "input_tokens_observed": 0,
        "output_tokens_observed": 0,
        "raw_content_in_attestation": False,
    }


def read_codex_execution_identity(sessions_root: Path, provider_conversation_id: str) -> dict[str, Any]:
    matches = list(sessions_root.rglob(f"*{provider_conversation_id}.jsonl"))
    if len(matches) != 1:
        return {"identity_observed": False, "match_count": len(matches)}
    path = matches[0]
    models: set[str] = set()
    providers: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        item = json.loads(line)
        payload = item.get("payload", {}) if isinstance(item, dict) else {}
        if not isinstance(payload, dict):
            continue
        if isinstance(payload.get("model"), str):
            models.add(payload["model"])
        state = payload.get("state", {})
        if isinstance(state, dict) and isinstance(state.get("model"), str):
            models.add(state["model"])
        if isinstance(payload.get("model_provider"), str):
            providers.add(payload["model_provider"])
    return {
        "identity_observed": len(models) == 1 and len(providers) == 1,
        "effective_models": sorted(models),
        "effective_providers": sorted(providers),
        "native_rollout_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "raw_content_in_attestation": False,
    }


def read_session_metadata(database: Path, session_id: str) -> dict[str, Any]:
    uri = f"file:{database}?mode=ro"
    with sqlite3.connect(uri, uri=True) as connection:
        row = connection.execute(
            "SELECT provider_conversation_id, workspace_path FROM sessions WHERE id = ?",
            (session_id,),
        ).fetchone()
        schema = connection.execute(
            "SELECT name, sql FROM sqlite_master WHERE type = 'table' AND name IN "
            "('sessions', 'conversations', 'conversation_messages', 'conversation_provider_events') "
            "ORDER BY name"
        ).fetchall()
    if not row or not row[0] or not row[1]:
        return {"metadata_observed": False}
    return {
        "metadata_observed": True,
        "provider_conversation_id": str(row[0]),
        "workspace_path": str(row[1]),
        "schema_sha256": sha256_text(json.dumps(schema, separators=(",", ":"))),
    }


def evidence_passes(evidence: dict[str, Any], identity: dict[str, Any], configured_model: str) -> bool:
    return all(
        (
            configured_model == "gpt-5.4",
            evidence.get("required_provider_sequence_complete") is True,
            evidence.get("expected_reply_observed") is True,
            int(evidence.get("output_tokens_observed", 0)) > 0,
            evidence.get("raw_content_in_attestation") is False,
            identity.get("identity_observed") is True,
            identity.get("effective_models") == [configured_model],
            identity.get("effective_providers") == ["openai"],
        )
    )
