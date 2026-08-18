"""mini-SWE-agent model adapter backed by the authenticated Grok CLI.

The CLI is used only as a model transport. Its own tools, web access, and
memory are disabled; mini-SWE-agent remains responsible for every command and
environment interaction.
"""

from __future__ import annotations

import json
import subprocess
import tempfile
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


RESPONSE_SCHEMA = json.dumps(
    {
        "type": "object",
        "properties": {
            "content": {"type": "string"},
            "command": {"type": "string"},
        },
        "required": ["content", "command"],
        "additionalProperties": False,
    },
    separators=(",", ":"),
)


class GrokCliExecutionError(RuntimeError):
    """The authenticated CLI failed before returning a model response."""


class GrokCliSessionCleanupError(RuntimeError):
    """A newly created CLI session could not be removed."""


@dataclass(frozen=True)
class GrokCliModelConfig:
    model_name: str = "grok-4.5"
    executable: str = "grok"
    timeout_seconds: int = 180
    observation_limit: int = 10_000
    cleanup_sessions: bool = True


class GrokCliModel:
    """Implement mini-SWE-agent's model protocol through Grok CLI OAuth."""

    def __init__(self, **kwargs: Any) -> None:
        allowed = {field.name for field in GrokCliModelConfig.__dataclass_fields__.values()}
        self.config = GrokCliModelConfig(**{key: value for key, value in kwargs.items() if key in allowed})

    def query(self, messages: list[dict[str, Any]], **_: Any) -> dict[str, Any]:
        prompt = (
            "You are the model inside mini-SWE-agent. Review the JSON conversation below. "
            "Return concise reasoning in content and exactly one shell command in command. "
            "Do not call tools yourself. To finish, set command exactly to "
            "echo COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT.\n\n"
            + json.dumps(messages, ensure_ascii=False, separators=(",", ":"))
        )
        with tempfile.TemporaryDirectory(prefix="agentic-sdlc-grok-model-", dir="/private/tmp") as directory:
            invocation_root = Path(directory)
            prompt_path = invocation_root / "prompt.txt"
            prompt_path.write_text(prompt, encoding="utf-8")
            prompt_path.chmod(0o600)
            completed = subprocess.run(
                (
                    self.config.executable,
                    "--prompt-file",
                    str(prompt_path),
                    "--cwd",
                    str(invocation_root),
                    "--verbatim",
                    "--model",
                    self.config.model_name,
                    "--json-schema",
                    RESPONSE_SCHEMA,
                    "--disable-web-search",
                    "--no-memory",
                    "--tools",
                    "",
                    "--max-turns",
                    "1",
                ),
                cwd=invocation_root,
                capture_output=True,
                text=True,
                check=False,
                timeout=self.config.timeout_seconds,
            )
        if completed.returncode != 0:
            raise GrokCliExecutionError(f"Grok CLI exited with status {completed.returncode}")
        outer = json.loads(completed.stdout)
        session_id = outer.get("sessionId")
        try:
            payload = outer.get("structuredOutput")
            if not isinstance(payload, dict):
                text = outer.get("text")
                payload = json.loads(text) if isinstance(text, str) else None
            if not isinstance(payload, dict) or not isinstance(payload.get("command"), str):
                raise ValueError("Grok CLI returned no structured command")
            content = payload.get("content", "")
            if not isinstance(content, str):
                raise ValueError("Grok CLI returned invalid structured content")
            cost = float(outer.get("total_cost_usd") or 0.0)
        finally:
            if self.config.cleanup_sessions and isinstance(session_id, str):
                self._delete_session(session_id)
        return {
            "role": "assistant",
            "content": content,
            "extra": {
                "actions": [{"command": payload["command"]}],
                "cost": cost,
                "timestamp": time.time(),
            },
        }

    def _delete_session(self, session_id: str) -> None:
        try:
            canonical = str(uuid.UUID(session_id))
        except ValueError as exc:
            raise ValueError("Grok CLI returned an invalid session identifier") from exc
        returncode = -1
        for attempt in range(3):
            cleanup = subprocess.run(
                (self.config.executable, "sessions", "delete", canonical),
                capture_output=True,
                text=True,
                check=False,
                timeout=30,
            )
            returncode = cleanup.returncode
            if returncode == 0:
                return
            if attempt < 2:
                time.sleep(0.25 * (attempt + 1))
        raise GrokCliSessionCleanupError(f"Grok CLI session cleanup exited with status {returncode}")

    def format_message(self, **kwargs: Any) -> dict[str, Any]:
        return dict(kwargs)

    def format_observation_messages(
        self,
        message: dict[str, Any],
        outputs: list[Any],
        template_vars: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        del message, template_vars
        rendered: list[dict[str, Any]] = []
        for output in outputs:
            value = output if isinstance(output, dict) else vars(output)
            text = str(value.get("output", ""))
            if len(text) > self.config.observation_limit:
                half = self.config.observation_limit // 2
                text = text[:half] + "\n[...elided...]\n" + text[-half:]
            rendered.append(
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "returncode": value.get("returncode"),
                            "output": text,
                            "exception_info": value.get("exception_info"),
                        },
                        ensure_ascii=False,
                    ),
                }
            )
        return rendered

    def get_template_vars(self, **_: Any) -> dict[str, Any]:
        return {"model_name": self.config.model_name}

    def serialize(self) -> dict[str, Any]:
        config = asdict(self.config)
        config.pop("executable", None)
        return {
            "info": {
                "config": {
                    "model": config,
                    "model_type": f"{self.__class__.__module__}.{self.__class__.__name__}",
                    "auth_transport": "native-cli-oauth",
                }
            }
        }
