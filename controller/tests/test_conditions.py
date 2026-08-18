from pathlib import Path
import unittest

from benchmark_controller.conditions import load_conditions


class ConditionMatrixTests(unittest.TestCase):
    def test_protocol_matrix_has_eighteen_conditions(self) -> None:
        path = Path(__file__).resolve().parents[2] / "protocol" / "conditions-v1.0.json"
        document = load_conditions(path)
        self.assertEqual(len(document["conditions"]), 18)

    def test_protocol_v1_1_preserves_condition_matrix(self) -> None:
        path = Path(__file__).resolve().parents[2] / "protocol" / "conditions-v1.1.json"
        document = load_conditions(path)
        self.assertEqual(document["protocol_version"], "v1.1")
        self.assertEqual(len(document["conditions"]), 18)

    def test_protocol_v1_2_has_six_ade_agentskit_conditions(self) -> None:
        path = Path(__file__).resolve().parents[2] / "protocol" / "conditions-v1.2.json"
        document = load_conditions(path)
        self.assertEqual(document["protocol_version"], "v1.2")
        self.assertEqual(set(document["factors"]), {"ade", "agentskit"})
        self.assertEqual(len(document["conditions"]), 6)
