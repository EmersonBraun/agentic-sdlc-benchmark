import importlib.util
from pathlib import Path
import unittest


class OrcaV12ConditionProbeTests(unittest.TestCase):
    def test_probe_is_importable_and_freezes_task_identity(self) -> None:
        path = Path(__file__).resolve().parents[1] / "scripts/probe_orca_v12_condition.py"
        spec = importlib.util.spec_from_file_location("probe_orca_v12_condition", path)
        module = importlib.util.module_from_spec(spec)
        assert spec and spec.loader
        spec.loader.exec_module(module)
        self.assertEqual(module.TASK_ID, "pilot_greenfield_service_readiness")
        self.assertEqual(module.EXPECTED_ORCA_VERSION, "1.4.184")
