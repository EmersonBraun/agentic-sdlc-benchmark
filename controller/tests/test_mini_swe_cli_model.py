import json
import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch

from benchmark_controller.mini_swe_cli_model import GrokCliExecutionError, GrokCliModel


class GrokCliModelTests(unittest.TestCase):
    @patch("benchmark_controller.mini_swe_cli_model.subprocess.run")
    def test_query_uses_cli_only_and_returns_one_mini_swe_action(self, run) -> None:
        run.return_value = subprocess.CompletedProcess(
            args=(),
            returncode=0,
            stdout=json.dumps(
                {
                    "structuredOutput": {"content": "Inspect files", "command": "pwd"},
                    "total_cost_usd": 0.01,
                    "sessionId": "00000000-0000-4000-8000-000000000001",
                }
            ),
            stderr="",
        )
        model = GrokCliModel(model_name="grok-4.5")

        result = model.query([{"role": "user", "content": "Solve the task"}])

        self.assertEqual(result["extra"]["actions"], [{"command": "pwd"}])
        argv = run.call_args_list[0].args[0]
        self.assertIn("--disable-web-search", argv)
        self.assertIn("--no-memory", argv)
        self.assertEqual(argv[argv.index("--tools") + 1], "")
        self.assertEqual(argv[argv.index("--model") + 1], "grok-4.5")
        self.assertNotIn("Solve the task", argv)
        self.assertIn("--prompt-file", argv)
        self.assertIn("--verbatim", argv)
        self.assertFalse(Path(argv[argv.index("--prompt-file") + 1]).exists())
        self.assertEqual(
            run.call_args_list[1].args[0],
            (
                "grok",
                "sessions",
                "delete",
                "00000000-0000-4000-8000-000000000001",
            ),
        )

    @patch("benchmark_controller.mini_swe_cli_model.subprocess.run")
    def test_query_fails_closed_on_cli_error(self, run) -> None:
        run.return_value = subprocess.CompletedProcess(args=(), returncode=7, stdout="", stderr="secret")
        with self.assertRaisesRegex(GrokCliExecutionError, "status 7"):
            GrokCliModel().query([])

    def test_serialization_excludes_executable_and_credentials(self) -> None:
        serialized = GrokCliModel(executable="/private/grok").serialize()
        text = json.dumps(serialized)
        self.assertNotIn("/private/grok", text)
        self.assertIn("native-cli-oauth", text)


if __name__ == "__main__":
    unittest.main()
