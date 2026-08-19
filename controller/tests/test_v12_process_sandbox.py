from pathlib import Path
import subprocess
import tempfile
import unittest

from benchmark_controller.v12_process_sandbox import sandbox_argv


class V12ProcessSandboxTests(unittest.TestCase):
    @unittest.skipUnless(Path("/usr/bin/sandbox-exec").is_file(), "requires macOS sandbox")
    def test_measured_agent_process_cannot_read_private_evaluation(self):
        with tempfile.TemporaryDirectory() as directory:
            private = Path(directory) / "private"
            private.mkdir()
            secret = private / "oracle.txt"
            secret.write_text("hidden")

            completed = subprocess.run(
                sandbox_argv(("python3", "-c", f"open({str(secret)!r}).read()"), private),
                capture_output=True, check=False,
            )

            self.assertNotEqual(completed.returncode, 0)


if __name__ == "__main__":
    unittest.main()
