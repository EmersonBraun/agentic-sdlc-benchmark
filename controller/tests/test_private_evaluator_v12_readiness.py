import json
from pathlib import Path
import unittest


class PrivateEvaluatorV12ReadinessTests(unittest.TestCase):
    def test_public_attestation_is_bounded_and_passed(self) -> None:
        root = Path(__file__).resolve().parents[2]
        value = json.loads((root / "adapters/private-evaluator-v1.2-readiness.json").read_text())
        self.assertEqual(value["schema_version"], "private-evaluator-readiness-v1.2")
        self.assertEqual(value["status"], "passed")
        self.assertFalse(value["analysis_eligible"])
        self.assertFalse(value["private_source_disclosed"])
        self.assertFalse(value["raw_private_output_persisted_publicly"])
        self.assertTrue(all(value["hard_gates"].values()))
        self.assertEqual(value["hidden_test_summary"]["failed"], 0)
        for key in (
            "reference_solution_patch_sha256", "evidence_plan_sha256",
            "reference_attestation_sha256",
        ):
            self.assertEqual(len(value[key]), 64)


if __name__ == "__main__":
    unittest.main()
