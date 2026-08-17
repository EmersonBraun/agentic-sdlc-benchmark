import unittest
from pathlib import Path

from benchmark_controller.session_parity import load_session_parity_manifest


class SessionParityManifestTests(unittest.TestCase):
    def test_published_manifest_is_non_executable_by_default(self) -> None:
        root = Path(__file__).resolve().parents[2]
        manifest = load_session_parity_manifest(root / "adapters" / "session-parity-test-v1.0.json")
        self.assertEqual(manifest.target_ades, ("agent-orchestrator", "compozy", "orca"))
        self.assertEqual(manifest.fixture_product_id, "greenfield")
        self.assertTrue(manifest.operator_confirmation_required)
        self.assertFalse(manifest.default_executable)
