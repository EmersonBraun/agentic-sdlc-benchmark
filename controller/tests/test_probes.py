import unittest

from benchmark_controller.probes import ProbeSpec, assert_probe_suite, run_probe


class ProbeTests(unittest.TestCase):
    def test_probe_uses_argv_and_hashes_output(self) -> None:
        result = run_probe(
            ProbeSpec("python-version", ("python3", "--version"), ("Python",))
        )
        self.assertTrue(result.passed)
        self.assertEqual(len(result.output_sha256), 64)
        self.assertNotIn("secret", result.output_preview)

    def test_probe_failure_is_explicit(self) -> None:
        result = run_probe(ProbeSpec("missing", ("definitely-not-a-command",)))
        self.assertFalse(result.passed)
        with self.assertRaisesRegex(RuntimeError, "missing"):
            assert_probe_suite([result])

    def test_probe_timeout_is_explicit(self) -> None:
        result = run_probe(
            ProbeSpec("timeout", ("python3", "-c", "import time; time.sleep(0.05)")),
            timeout_seconds=0.001,
        )
        self.assertTrue(result.timed_out)
        self.assertFalse(result.passed)
