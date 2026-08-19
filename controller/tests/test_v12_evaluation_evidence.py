import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

from benchmark_controller.v12_evaluation_evidence import (
    ControllerEvidenceAttestation,
    blind_snapshot,
)


def sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


class V12EvaluationEvidenceTests(unittest.TestCase):
    def repository(self, root: Path) -> str:
        subprocess.run(("git", "init", "-q", str(root)), check=True)
        subprocess.run(("git", "-C", str(root), "config", "user.email", "test@example.test"), check=True)
        subprocess.run(("git", "-C", str(root), "config", "user.name", "Test"), check=True)
        (root / "src").mkdir()
        (root / "src/app.py").write_text("print('ok')\n")
        (root / "AGENTS.md").write_text("treatment leak")
        (root / "src/CLAUDE.md").write_text("instruction leak")
        (root / ".codex").mkdir()
        (root / ".codex/config.toml").write_text("model='other'")
        subprocess.run(("git", "-C", str(root), "add", "."), check=True)
        subprocess.run(("git", "-C", str(root), "commit", "-qm", "fixture"), check=True)
        return subprocess.run(
            ("git", "-C", str(root), "rev-parse", "HEAD"),
            capture_output=True, text=True, check=True,
        ).stdout.strip()

    def test_blind_snapshot_has_no_git_or_instruction_surfaces(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            commit = self.repository(root)
            with blind_snapshot(root, expected_commit=commit) as snapshot:
                self.assertTrue((snapshot.path / "src/app.py").is_file())
                self.assertFalse((snapshot.path / ".git").exists())
                self.assertFalse((snapshot.path / "AGENTS.md").exists())
                self.assertFalse((snapshot.path / "src/CLAUDE.md").exists())
                self.assertFalse((snapshot.path / ".codex").exists())
                self.assertNotIn("run_", str(snapshot.path))
                self.assertEqual(len(snapshot.tree_sha256), 64)
            self.assertFalse(snapshot.path.exists())

    def test_dirty_source_is_rejected_before_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            commit = self.repository(root)
            (root / "src/app.py").write_text("dirty")
            with self.assertRaisesRegex(RuntimeError, "clean commit"):
                with blind_snapshot(root, expected_commit=commit):
                    pass

    def test_attestation_binds_identity_ledger_and_command_results(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ledger = b"one\ntwo\n"
            commands = []
            for kind in ("build", "typecheck", "ci", "hidden-tests", "ledger-validation"):
                commands.append({
                    "kind": kind, "command_sha256": "a" * 64,
                    "output_sha256": "b" * 64, "exit_code": 0,
                })
            document = {
                "schema_version": "controller-evidence-attestation-v1.2",
                "protocol_version": "v1.2", "task_id": "pilot_task",
                "task_manifest_sha256": "c" * 64, "product_commit": "d" * 40,
                "private_source_commit": "e" * 40,
                "hard_gates": {name: True for name in (
                    "build", "typecheck", "ci", "essential-hidden-tests", "ledger"
                )},
                "hidden_test_summary": {
                    "total": 4, "passed": 4, "failed": 0,
                    "critical_mutants_killed": True, "noncritical_mutant_kill_rate": 0.9,
                },
                "ledger_prefix_sha256": sha(ledger), "command_evidence": commands,
            }
            path = root / "attestation.json"
            path.write_text(json.dumps(document))
            attestation = ControllerEvidenceAttestation.load(
                path, task_id="pilot_task", task_manifest_sha256="c" * 64,
                product_commit="d" * 40, ledger_prefix=ledger,
            )
            self.assertEqual(attestation.public_summary()["hard_gates"]["ledger"], True)

    def test_attestation_rejects_contradictory_hidden_gate(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ledger = b"ledger"
            commands = [{
                "kind": kind, "command_sha256": "a" * 64,
                "output_sha256": "b" * 64, "exit_code": 0,
            } for kind in ("build", "typecheck", "ci", "hidden-tests", "ledger-validation")]
            document = {
                "schema_version": "controller-evidence-attestation-v1.2",
                "protocol_version": "v1.2", "task_id": "pilot_task",
                "task_manifest_sha256": "c" * 64, "product_commit": "d" * 40,
                "private_source_commit": "e" * 40,
                "hard_gates": {name: True for name in (
                    "build", "typecheck", "ci", "essential-hidden-tests", "ledger"
                )},
                "hidden_test_summary": {
                    "total": 4, "passed": 3, "failed": 1,
                    "critical_mutants_killed": True, "noncritical_mutant_kill_rate": 0.9,
                },
                "ledger_prefix_sha256": sha(ledger), "command_evidence": commands,
            }
            path = root / "attestation.json"
            path.write_text(json.dumps(document))
            with self.assertRaisesRegex(ValueError, "contradicts"):
                ControllerEvidenceAttestation.load(
                    path, task_id="pilot_task", task_manifest_sha256="c" * 64,
                    product_commit="d" * 40, ledger_prefix=ledger,
                )
