import importlib.util
from pathlib import Path
import unittest


class AOV12ConditionProbeTests(unittest.TestCase):
    def test_probe_is_importable_and_freezes_task_identity(self) -> None:
        path = Path(__file__).resolve().parents[1] / "scripts/probe_ao_v12_condition.py"
        spec = importlib.util.spec_from_file_location("probe_ao_v12_condition", path)
        module = importlib.util.module_from_spec(spec)
        assert spec and spec.loader
        spec.loader.exec_module(module)
        self.assertEqual(module.TASK_ID, "pilot_greenfield_service_readiness")
        self.assertEqual(module.BASE_COMMIT, "032045401c38d0d7f6168ade1cf2053f503e4acc")

    def test_missing_workspace_path_does_not_resolve_to_current_directory(self) -> None:
        source = (
            Path(__file__).resolve().parents[1] / "scripts/probe_ao_v12_condition.py"
        ).read_text()
        self.assertIn("if not workspace_value or not workspace.is_dir()", source)
        self.assertIn("session_registry.append(session_id)", source)
        self.assertLess(
            source.index("session_registry.append(session_id)"),
            source.index('if spawned.returncode or not session_id:'),
        )
