import hashlib
import json
import unittest
from pathlib import Path

from benchmark_controller.compozy_grok import summarize_events, validate_provider_config


class CompozyGrokTests(unittest.TestCase):
    def test_accepts_only_frozen_native_cli_provider(self) -> None:
        argv = validate_provider_config({
            "command": "/opt/bin/grok agent --model grok-4.5 --reasoning-effort low stdio",
            "auth_mode": "native_cli",
            "env_policy": "filtered",
            "home_policy": "operator",
        })
        self.assertEqual(argv[-1], "stdio")

    def test_rejects_xai_api_or_unpinned_runtime(self) -> None:
        for provider in (
            {
                "command": "npx pi-acp",
                "auth_mode": "bound_secret",
                "env_policy": "filtered",
                "home_policy": "operator",
            },
            {
                "command": "grok agent stdio",
                "auth_mode": "native_cli",
                "env_policy": "filtered",
                "home_policy": "operator",
            },
        ):
            with self.assertRaises(ValueError):
                validate_provider_config(provider)

    def test_sentinel_must_come_from_agent_message(self) -> None:
        summary = summarize_events([
            {"type": "hook.dispatch.start", "content": {
                "prompt_runtime": {"provider": "codex"},
            }},
            {"type": "user_message", "content": {"text": "READY"}},
            {"type": "agent_message", "content": {
                "text": "REA", "prompt_runtime": {"provider": "grok-cli"},
            }},
            {"type": "agent_message", "content": {
                "text": "DY", "prompt_runtime": {"provider": "grok-cli"},
            }},
            {"type": "done", "content": {"prompt_runtime": {"provider": "grok-cli"}}},
        ], "READY")
        self.assertTrue(summary["sentinel_observed"])
        self.assertTrue(summary["done_observed"])
        self.assertEqual(summary["providers"], ["grok-cli"])

    def test_canonical_attestation_is_source_bound_and_scoped(self) -> None:
        root = Path(__file__).resolve().parents[2]
        document = json.loads(
            (root / "adapters/compozy-grok-cli-v1.2-readiness-attestation.json").read_text()
        )
        self.assertEqual(document["status"], "passed")
        self.assertFalse(document["analysis_eligible"])
        self.assertFalse(document["provider"]["api_credential_absence_observed"])
        self.assertFalse(document["provider"]["runtime_reported_model_observed"])
        self.assertEqual(document["provider"]["compozy_bound_credential_slots"], 0)
        self.assertTrue(document["workspace"]["unchanged"])
        self.assertEqual(document["cleanup"]["new_grok_process_residual_count"], 0)
        for relative, expected in document["source_hashes"].items():
            actual = hashlib.sha256((root / relative).read_bytes()).hexdigest()
            self.assertEqual(expected, actual)


if __name__ == "__main__":
    unittest.main()
