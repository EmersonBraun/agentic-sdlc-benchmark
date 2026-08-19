"""Production factories for the six-condition v1.2 native runtime."""

from __future__ import annotations

from pathlib import Path

from .agent_orchestrator_v12_executor import AgentOrchestratorV12RoleExecutor
from .codex_evaluator_v12 import CodexEvaluatorV12RoleExecutor, CodexV12CompletionVerifier
from .compozy_v12_executor import CompozyV12RoleExecutor
from .orca_v12_executor import OrcaV12RoleExecutor
from .v12_native_backend import V12RoleExecutor
from .compozy_v12_executor import SubprocessCompozyTransport
from .agent_orchestrator_v12_executor import SubprocessAOTransport
from .orca_v12_executor import SubprocessOrcaTransport


def build_v12_role_executor(
    ade: str, *, control_root: Path, ao_project: str, private_evaluation_root: Path,
) -> tuple[V12RoleExecutor, CodexV12CompletionVerifier]:
    """Resolve one frozen ADE without fallback and share one neutral evaluator."""

    evaluator = CodexEvaluatorV12RoleExecutor()
    if ade == "compozy":
        executor: V12RoleExecutor = CompozyV12RoleExecutor(
            control_root / "compozy",
            transport=SubprocessCompozyTransport(denied_root=private_evaluation_root),
            evaluator=evaluator,
        )
    elif ade == "agent-orchestrator":
        executor = AgentOrchestratorV12RoleExecutor(
            ao_project, transport=SubprocessAOTransport(private_evaluation_root),
            evaluator=evaluator,
        )
    elif ade == "orca":
        executor = OrcaV12RoleExecutor(
            transport=SubprocessOrcaTransport(denied_root=private_evaluation_root),
            evaluator=evaluator,
        )
    else:
        raise ValueError(f"unsupported v1.2 ADE: {ade!r}")
    return executor, CodexV12CompletionVerifier(evaluator)
