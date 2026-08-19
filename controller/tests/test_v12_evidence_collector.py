import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

from benchmark_controller.v12_evidence_collector import ControllerEvidenceCollector
from benchmark_controller.v12_evaluation_evidence import ControllerEvidenceAttestation


class ControllerEvidenceCollectorTests(unittest.TestCase):
    @staticmethod
    def commit_private_plan(plan: Path) -> str:
        subprocess.run(("git", "init", "-q"), cwd=plan.parent, check=True)
        subprocess.run(("git", "config", "user.email", "private@example.test"), cwd=plan.parent, check=True)
        subprocess.run(("git", "config", "user.name", "Private Test"), cwd=plan.parent, check=True)
        subprocess.run(("git", "add", "."), cwd=plan.parent, check=True)
        subprocess.run(("git", "commit", "-qm", "private fixture"), cwd=plan.parent, check=True)
        return subprocess.run(
            ("git", "rev-parse", "HEAD"), cwd=plan.parent,
            capture_output=True, text=True, check=True,
        ).stdout.strip()

    def test_executes_private_plan_and_emits_only_bounded_attestation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            worktree = root / "product"
            worktree.mkdir()
            (worktree / "task.manifest.json").write_text("{}")
            subprocess.run(("git", "init", "-q"), cwd=worktree, check=True)
            subprocess.run(("git", "config", "user.email", "test@example.test"), cwd=worktree, check=True)
            subprocess.run(("git", "config", "user.name", "Test"), cwd=worktree, check=True)
            subprocess.run(("git", "add", "."), cwd=worktree, check=True)
            subprocess.run(("git", "commit", "-qm", "fixture"), cwd=worktree, check=True)
            commit = subprocess.run(
                ("git", "rev-parse", "HEAD"), cwd=worktree,
                capture_output=True, text=True, check=True,
            ).stdout.strip()
            bundle = root / "bundle"
            bundle.mkdir()
            ledger = bundle / "ledger.jsonl"
            ledger.write_text('{"event":"fixture"}\n')
            plan = root / "private" / "plan.json"
            plan.parent.mkdir()
            commands = {}
            for kind in ("build", "typecheck", "ci", "ledger-validation"):
                commands[kind] = {"argv": ["/usr/bin/true"], "timeout_seconds": 5}
            commands["hidden-tests"] = {
                "argv": [
                    "{private_source}/emit-hidden-summary",
                    json.dumps({
                        "total": 5, "passed": 5, "failed": 0,
                        "critical_mutants_killed": True,
                        "noncritical_mutant_kill_rate": 0.9,
                    }),
                ],
                "timeout_seconds": 5,
            }
            plan.write_text(json.dumps({
                "schema_version": "controller-evidence-plan-v1.2",
                "task_id": "pilot_task",
                "commands": commands,
            }))
            (plan.parent / "emit-hidden-summary").symlink_to("/bin/echo")
            private_commit = self.commit_private_plan(plan)

            output = bundle / "private-evaluation/controller-attestation.json"
            result = ControllerEvidenceCollector().collect(
                plan_path=plan, output_path=output, worktree=worktree,
                ledger_path=ledger, task_id="pilot_task",
                task_manifest_sha256="c" * 64, product_commit=commit,
            )

            self.assertEqual(result, output.resolve())
            raw = output.read_text()
            self.assertNotIn(str(plan.parent), raw)
            self.assertNotIn("/usr/bin/true", raw)
            attestation = ControllerEvidenceAttestation.load(
                output, task_id="pilot_task", task_manifest_sha256="c" * 64,
                product_commit=commit, ledger_prefix=ledger.read_bytes(),
            )
            self.assertTrue(all(attestation.document["hard_gates"].values()))
            self.assertEqual(attestation.document["private_source_commit"], private_commit)
            self.assertEqual(
                attestation.document["ledger_prefix_sha256"],
                hashlib.sha256(ledger.read_bytes()).hexdigest(),
            )

    def test_failed_collection_removes_stale_attestation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            worktree = root / "product"
            worktree.mkdir()
            (worktree / "tracked").write_text("fixture")
            subprocess.run(("git", "init", "-q"), cwd=worktree, check=True)
            subprocess.run(("git", "config", "user.email", "test@example.test"), cwd=worktree, check=True)
            subprocess.run(("git", "config", "user.name", "Test"), cwd=worktree, check=True)
            subprocess.run(("git", "add", "."), cwd=worktree, check=True)
            subprocess.run(("git", "commit", "-qm", "fixture"), cwd=worktree, check=True)
            commit = subprocess.run(
                ("git", "rev-parse", "HEAD"), cwd=worktree,
                capture_output=True, text=True, check=True,
            ).stdout.strip()
            bundle = root / "bundle"
            private = bundle / "private-evaluation"
            private.mkdir(parents=True)
            output = private / "controller-attestation.json"
            output.write_text("stale")
            ledger = bundle / "ledger.jsonl"
            ledger.write_text("")
            commands = {
                kind: {"argv": ["/usr/bin/true"], "timeout_seconds": 5}
                for kind in ("build", "typecheck", "ci", "ledger-validation")
            }
            commands["hidden-tests"] = {
                "argv": ["/bin/echo", "not-json"], "timeout_seconds": 5,
            }
            plan = private / "source/evidence-plan.json"
            plan.parent.mkdir()
            plan.write_text(json.dumps({
                "schema_version": "controller-evidence-plan-v1.2",
                "task_id": "pilot_task",
                "commands": commands,
            }))
            self.commit_private_plan(plan)

            with self.assertRaises(ValueError):
                ControllerEvidenceCollector().collect(
                    plan_path=plan, output_path=output, worktree=worktree,
                    ledger_path=ledger, task_id="pilot_task",
                    task_manifest_sha256="c" * 64, product_commit=commit,
                )
            self.assertFalse(output.exists())

    def test_materializes_frozen_private_source_without_hardlinks(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            source.mkdir()
            plan = source / "evidence-plan.json"
            plan.write_text("{}")
            commit = self.commit_private_plan(plan)
            target = root / "bundle/private-evaluation/source"

            ControllerEvidenceCollector(source)._materialize_source(target)

            observed = subprocess.run(
                ("git", "rev-parse", "HEAD"), cwd=target,
                capture_output=True, text=True, check=True,
            ).stdout.strip()
            self.assertEqual(observed, commit)
            self.assertNotEqual((source / ".git/objects").stat().st_ino, (target / ".git/objects").stat().st_ino)


if __name__ == "__main__":
    unittest.main()
