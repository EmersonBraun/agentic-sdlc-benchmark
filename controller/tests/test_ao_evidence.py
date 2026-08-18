import sqlite3
import tempfile
import unittest
from pathlib import Path

from benchmark_controller.ao_evidence import evidence_passes, read_provider_evidence


class AgentOrchestratorEvidenceTests(unittest.TestCase):
    def _database(self, root: Path, *, include_completion: bool = True) -> Path:
        database = root / "ao.db"
        with sqlite3.connect(database) as connection:
            connection.executescript(
                """
                CREATE TABLE conversations (
                    id TEXT PRIMARY KEY, session_id TEXT, usage_input_tokens INTEGER,
                    usage_output_tokens INTEGER
                );
                CREATE TABLE conversation_messages (
                    id TEXT PRIMARY KEY, conversation_id TEXT, sequence INTEGER,
                    role TEXT, text TEXT, streaming INTEGER
                );
                CREATE TABLE conversation_provider_events (
                    id INTEGER PRIMARY KEY, session_id TEXT, method TEXT
                );
                INSERT INTO conversations VALUES ('c1', 's1', 12, 3);
                INSERT INTO conversation_messages VALUES ('m1', 'c1', 1, 'assistant', 'PARITY_PROBE_READY', 0);
                """
            )
            methods = ["turn.started", "usage", "turn.completed"]
            if include_completion:
                methods.append("message.completed")
            connection.executemany(
                "INSERT INTO conversation_provider_events(session_id, method) VALUES ('s1', ?)",
                ((method,) for method in methods),
            )
        return database

    def test_accepts_complete_redacted_gpt54_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            evidence = read_provider_evidence(self._database(Path(directory)), "s1", "PARITY_PROBE_READY")
        self.assertTrue(evidence_passes(evidence, "gpt-5.4"))
        self.assertNotIn("assistant_text", evidence)
        self.assertEqual(len(evidence["assistant_reply_sha256"]), 64)

    def test_rejects_wrong_model_or_incomplete_lifecycle(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            evidence = read_provider_evidence(
                self._database(Path(directory), include_completion=False), "s1", "PARITY_PROBE_READY"
            )
        self.assertFalse(evidence_passes(evidence, "gpt-5.4"))
        evidence["required_provider_events_complete"] = True
        self.assertFalse(evidence_passes(evidence, "gpt-5.3-codex"))
