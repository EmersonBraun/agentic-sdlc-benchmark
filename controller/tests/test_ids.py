import unittest

from benchmark_controller.ids import validate_id


class IdentifierTests(unittest.TestCase):
    def test_valid_identifiers(self) -> None:
        self.assertEqual(validate_id("run_main_001", "run"), "run_main_001")
        self.assertEqual(validate_id("main_greenfield_feature_001", "task"), "main_greenfield_feature_001")
        self.assertEqual(validate_id("evt_abc-123", "event"), "evt_abc-123")

    def test_invalid_identifier_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            validate_id("main_task", "run")

    def test_unknown_kind_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            validate_id("run_001", "unknown")
