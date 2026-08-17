import unittest

from validate_result import validate_result


def _valid() -> dict:
    return {
        "schema_version": "1.0",
        "run_id": "run_example",
        "quality_pass": True,
        "product_quality_score": 91,
        "process_score": 88,
        "hard_gates": {"tests": True, "security": True},
        "hidden_test_summary": {"total": 10, "passed": 10, "failed": 0},
        "evaluator_status": "complete",
    }


class ValidateResultTests(unittest.TestCase):
    def test_valid_result(self) -> None:
        self.assertEqual(validate_result(_valid(), expected_run_id="run_example"), [])

    def test_rejects_incomplete_hidden_test_counts(self) -> None:
        result = _valid()
        result["hidden_test_summary"] = {"total": 10, "passed": 11, "failed": 0}
        self.assertIn("hidden_test_summary:invalid counts", validate_result(result))

    def test_rejects_run_mismatch_and_invalid_gate(self) -> None:
        result = _valid()
        result["hard_gates"] = {"tests": "passed"}
        errors = validate_result(result, expected_run_id="run_other")
        self.assertIn("run_id:mismatch", errors)
        self.assertIn("hard_gates:must be a non-empty boolean object", errors)


if __name__ == "__main__":
    unittest.main()
