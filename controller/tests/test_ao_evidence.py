import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from benchmark_controller.ao_evidence import (
    evidence_passes,
    read_codex_execution_identity,
    read_provider_evidence,
)


class AgentOrchestratorEvidenceTests(unittest.TestCase):
    def _database(self, root: Path, *, methods: list[str] | None = None) -> Path:
        database = root / "ao.db"
        with closing(sqlite3.connect(database)) as connection:
            connection.executescript(
                """
                CREATE TABLE conversations (
                    id TEXT PRIMARY KEY, session_id TEXT, usage_input_tokens INTEGER,
                    usage_output_tokens INTEGER, updated_at TEXT
                );
                CREATE TABLE conversation_messages (
                    id TEXT PRIMARY KEY, conversation_id TEXT, sequence INTEGER,
                    role TEXT, text TEXT, streaming INTEGER
                );
                CREATE TABLE conversation_provider_events (
                    id INTEGER PRIMARY KEY, session_id TEXT, conversation_id TEXT, method TEXT
                );
                INSERT INTO conversations VALUES ('c1', 's1', 12, 3, '2026-08-18T00:00:00Z');
                INSERT INTO conversation_messages VALUES ('m1', 'c1', 1, 'assistant', 'PARITY_PROBE_READY', 0);
                """
            )
            methods = methods or ["turn.started", "message.completed", "usage", "turn.completed"]
            connection.executemany(
                "INSERT INTO conversation_provider_events(session_id, conversation_id, method) VALUES ('s1', 'c1', ?)",
                ((method,) for method in methods),
            )
            connection.commit()
        return database

    def test_accepts_complete_redacted_gpt54_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            evidence = read_provider_evidence(self._database(root), "s1", "PARITY_PROBE_READY")
            rollout = root / "rollout-thread-1.jsonl"
            rollout.write_text('{"payload":{"model_provider":"openai","model":"gpt-5.4"}}\n')
            identity = read_codex_execution_identity(root, "thread-1")
        self.assertTrue(evidence_passes(evidence, identity, "gpt-5.4"))
        self.assertNotIn("assistant_text", evidence)
        self.assertEqual(len(evidence["assistant_reply_sha256"]), 64)

    def test_rejects_wrong_model_or_incomplete_lifecycle(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            evidence = read_provider_evidence(self._database(root, methods=["turn.started", "usage", "turn.completed"]), "s1", "PARITY_PROBE_READY")
            rollout = root / "rollout-thread-1.jsonl"
            rollout.write_text('{"payload":{"model_provider":"openai","model":"gpt-5.4"}}\n')
            identity = read_codex_execution_identity(root, "thread-1")
        self.assertFalse(evidence_passes(evidence, identity, "gpt-5.4"))
        evidence["required_provider_sequence_complete"] = True
        self.assertFalse(evidence_passes(evidence, identity, "gpt-5.3-codex"))

    def test_rejects_reordered_or_duplicate_required_events(self) -> None:
        for methods in (
            ["message.completed", "turn.started", "usage", "turn.completed"],
            ["turn.started", "message.completed", "message.completed", "usage", "turn.completed"],
        ):
            with self.subTest(methods=methods), tempfile.TemporaryDirectory() as directory:
                evidence = read_provider_evidence(self._database(Path(directory), methods=methods), "s1", "PARITY_PROBE_READY")
                self.assertFalse(evidence["required_provider_sequence_complete"])
