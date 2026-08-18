"""Redacted validation of Agent Orchestrator's persisted provider evidence."""

from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path
from typing import Any

REQUIRED_PROVIDER_EVENTS = frozenset(
    {"turn.started", "message.completed", "usage", "turn.completed"}
)


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def read_provider_evidence(database: Path, session_id: str, expected_reply: str) -> dict[str, Any]:
    """Read only bounded metadata from AO's datastore; never return message content."""

    uri = f"file:{database}?mode=ro"
    with sqlite3.connect(uri, uri=True) as connection:
        methods = {
            str(row[0])
            for row in connection.execute(
                "SELECT DISTINCT method FROM conversation_provider_events WHERE session_id = ?",
                (session_id,),
            )
        }
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
        "provider_event_types": sorted(methods & REQUIRED_PROVIDER_EVENTS),
        "required_provider_events_complete": REQUIRED_PROVIDER_EVENTS <= methods,
        "assistant_message_count": len(messages),
        "expected_reply_observed": assistant_text == expected_reply,
        "assistant_reply_sha256": sha256_text(assistant_text) if assistant_text else None,
        "input_tokens_observed": int(usage[0]) if usage else 0,
        "output_tokens_observed": int(usage[1]) if usage else 0,
        "raw_content_persisted": False,
    }


def evidence_passes(evidence: dict[str, Any], configured_model: str) -> bool:
    return all(
        (
            configured_model == "gpt-5.4",
            evidence.get("required_provider_events_complete") is True,
            evidence.get("expected_reply_observed") is True,
            int(evidence.get("output_tokens_observed", 0)) > 0,
            evidence.get("raw_content_persisted") is False,
        )
    )
