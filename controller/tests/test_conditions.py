from pathlib import Path
import unittest

from benchmark_controller.conditions import load_conditions


class ConditionMatrixTests(unittest.TestCase):
    def test_protocol_matrix_has_eighteen_conditions(self) -> None:
        path = Path(__file__).resolve().parents[2] / "protocol" / "conditions-v1.0.json"
        document = load_conditions(path)
        self.assertEqual(len(document["conditions"]), 18)
