import unittest

from benchmark_controller.compozy_lifecycle import normalize_compozy_event, normalize_compozy_events


class CompozyLifecycleTests(unittest.TestCase):
    def test_normalizes_lifecycle_metadata_and_hashable_identity(self) -> None:
        event = normalize_compozy_event(
            {
                "type": "done",
                "session_id": "sess-secret",
                "text": "raw model output must not be copied",
            }
        )
        self.assertEqual(
            event,
            {
                "event_name": "session.execution",
                "source_event_type": "done",
                "status": "completed",
                "duration_ms": 0,
                "entity_id": "sess-secret",
            },
        )
        self.assertNotIn("text", event)

    def test_filters_content_events(self) -> None:
        normalized = normalize_compozy_events(
            [
                {"type": "user_message", "text": "private prompt"},
                {"type": "agent_message", "text": "private response"},
                {"type": "tool_call", "arguments": {"secret": "private"}},
                {"type": "tool_result", "result": "private"},
                {"type": "done"},
            ]
        )
        self.assertEqual(len(normalized), 1)
        self.assertEqual(normalized[0]["event_name"], "session.execution")

    def test_unknown_event_fails_closed(self) -> None:
        with self.assertRaisesRegex(ValueError, "Unknown Compozy event type"):
            normalize_compozy_event({"type": "future_event"})
