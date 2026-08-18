import importlib.util
from pathlib import Path
import unittest


class CompozyV12ConditionProbeTests(unittest.TestCase):
    def test_probe_is_importable_and_freezes_task_identity(self) -> None:
        path = Path(__file__).resolve().parents[1] / "scripts/probe_compozy_v12_condition.py"
        spec = importlib.util.spec_from_file_location("probe_compozy_v12_condition", path)
        module = importlib.util.module_from_spec(spec)
        assert spec and spec.loader
        spec.loader.exec_module(module)
        self.assertEqual(module.TASK_ID, "pilot_greenfield_service_readiness")
        self.assertEqual(len(module.BASE_COMMIT), 40)

    def test_off_probe_materializes_an_empty_ledger_before_hashing(self) -> None:
        source = (
            Path(__file__).resolve().parents[1] / "scripts/probe_compozy_v12_condition.py"
        ).read_text()
        self.assertIn("args.ledger.touch(exist_ok=False)", source)
