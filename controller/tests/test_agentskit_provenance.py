import sys
import unittest
from pathlib import Path
from unittest.mock import patch


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from run_compozy_technical_pilot import _verify_public_checkout  # noqa: E402


class AgentsKitProvenanceTests(unittest.TestCase):
    @patch("run_compozy_technical_pilot._run")
    def test_accepts_only_exact_clean_public_checkout(self, run) -> None:
        run.side_effect = [
            (0, "9a03016932b9e3024604712183152025c0577fe4\n", 1),
            (0, "https://github.com/AgentsKit-io/doc-bridge.git\n", 1),
            (0, "", 1),
        ]
        evidence = _verify_public_checkout("doc_bridge", Path("/tmp/public-source"))
        self.assertTrue(evidence["provenance_verified"])
        self.assertTrue(evidence["working_tree_clean"])

    @patch("run_compozy_technical_pilot._run")
    def test_rejects_wrong_origin_before_execution(self, run) -> None:
        run.side_effect = [
            (0, "9a03016932b9e3024604712183152025c0577fe4\n", 1),
            (0, "https://example.invalid/private-fork\n", 1),
        ]
        with self.assertRaisesRegex(RuntimeError, "origin_mismatch"):
            _verify_public_checkout("doc_bridge", Path("/tmp/private-source"))

    @patch("run_compozy_technical_pilot._run")
    def test_rejects_dirty_checkout_before_execution(self, run) -> None:
        run.side_effect = [
            (0, "9a03016932b9e3024604712183152025c0577fe4\n", 1),
            (0, "https://github.com/AgentsKit-io/doc-bridge\n", 1),
            (0, " M src/index.ts\n", 1),
        ]
        with self.assertRaisesRegex(RuntimeError, "working_tree_not_clean"):
            _verify_public_checkout("doc_bridge", Path("/tmp/dirty-source"))


if __name__ == "__main__":
    unittest.main()
