"""Native ADE role bindings for protocol v1.2 technical execution."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Literal


Role = Literal["planner_requirements_lead", "executor_fixer"]


@dataclass(frozen=True)
class NativeRoleLaunch:
    ade: str
    role: Role
    provider: str
    model: str
    argv: tuple[str, ...]
    native_worktree: bool
    transport: str

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["argv"] = list(self.argv)
        return result


class V12ADEBackend:
    key: str

    def launch(self, role: Role) -> NativeRoleLaunch:
        raise NotImplementedError

    def topology(self) -> tuple[NativeRoleLaunch, NativeRoleLaunch]:
        planner = self.launch("planner_requirements_lead")
        executor = self.launch("executor_fixer")
        if planner.provider != "codex-cli" or planner.model != "gpt-5.4":
            raise RuntimeError(f"{self.key} planner binding drifted")
        if executor.provider != "grok-cli" or executor.model != "grok-4.5":
            raise RuntimeError(f"{self.key} executor binding drifted")
        return planner, executor


class OrcaV12Backend(V12ADEBackend):
    key = "orca"

    def launch(self, role: Role) -> NativeRoleLaunch:
        if role == "planner_requirements_lead":
            return NativeRoleLaunch(self.key, role, "codex-cli", "gpt-5.4", ("codex", "--model", "gpt-5.4"), True, "orca-terminal-dispatch")
        if role == "executor_fixer":
            return NativeRoleLaunch(self.key, role, "grok-cli", "grok-4.5", ("grok", "--model", "grok-4.5"), True, "orca-terminal-dispatch")
        raise ValueError(f"Unsupported role: {role!r}")


class AgentOrchestratorV12Backend(V12ADEBackend):
    key = "agent-orchestrator"

    def launch(self, role: Role) -> NativeRoleLaunch:
        if role == "planner_requirements_lead":
            return NativeRoleLaunch(self.key, role, "codex-cli", "gpt-5.4", ("ao", "spawn", "--kind", "orchestrator", "--harness", "codex"), True, "ao-native-session")
        if role == "executor_fixer":
            return NativeRoleLaunch(self.key, role, "grok-cli", "grok-4.5", ("ao", "spawn", "--kind", "worker", "--mode", "tui", "--harness", "grok"), True, "ao-native-session")
        raise ValueError(f"Unsupported role: {role!r}")


class CompozyV12Backend(V12ADEBackend):
    key = "compozy"

    def launch(self, role: Role) -> NativeRoleLaunch:
        if role == "planner_requirements_lead":
            return NativeRoleLaunch(self.key, role, "codex-cli", "gpt-5.4", ("compozy", "session", "prompt", "--provider", "codex", "--model", "gpt-5.4"), False, "compozy-acp")
        if role == "executor_fixer":
            return NativeRoleLaunch(self.key, role, "grok-cli", "grok-4.5", ("compozy", "session", "prompt", "--provider", "grok-cli", "--model", "grok-4.5"), False, "compozy-acp")
        raise ValueError(f"Unsupported role: {role!r}")


BACKENDS: dict[str, V12ADEBackend] = {
    "orca": OrcaV12Backend(),
    "agent-orchestrator": AgentOrchestratorV12Backend(),
    "compozy": CompozyV12Backend(),
}


def resolve_v12_backend(ade: str) -> V12ADEBackend:
    try:
        backend = BACKENDS[ade]
    except KeyError as exc:
        raise ValueError(f"Unknown v1.2 ADE: {ade!r}") from exc
    backend.topology()
    return backend
