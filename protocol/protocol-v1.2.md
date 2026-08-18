# Protocol v1.2

Status: approved for technical-pilot implementation; official collection is
blocked until all six conditions pass readiness and dry-run gates.

## Purpose of this revision

Protocol v1.2 narrows the primary causal question to ADE (ORCA, Agent
Orchestrator, or Compozy) and AgentsKit (OFF or ON), producing six matched
conditions. Third-party harnesses are removed as an independent factor. The
v1.0 and v1.1 designs remain immutable historical cohorts and must not be
pooled with v1.2.

## Fixed agent topology

Every condition uses Codex CLI with `gpt-5.4` for requirements, planning,
orchestration, and final integration decisions; Grok CLI with `grok-4.5` for
implementation and fixes; and Codex with `gpt-5.4-mini` for independent
evaluation. The ADE coordinates these roles through its native workflow and
worktree facilities. Native CLI agent loops are controlled runtime components,
not randomized harnesses. Silent provider, model, or role substitution is
prohibited.

## AgentsKit treatment

AgentsKit is the only treatment paired within each ADE. OFF uses no AgentsKit
runtime component. ON uses only declared public, open-source AgentsKit
components; private `agentskit-os` is prohibited. ON and OFF otherwise share
the task, base commit, ambiguity oracle, permissions, budgets, topology, ADE
workflow, evaluation, and stopping rules.

AgentsKit is assessed by incremental effects on product quality, SDLC process
quality, effective work, human intervention, regressions, variance, and
attributable overhead. Component ablations are secondary and require
preregistration before collection.

## Execution and evidence contract

Each run must start from the frozen task and base commit in a fresh worktree;
execute the full SDLC through the selected ADE; continue autonomously until
completion, budget boundary, or a predeclared HITL trigger; and record an
append-only ledger of actors, roles, tools, action digests, timestamps,
durations, state transitions, outputs, errors, interventions, and cleanup.

Effective work, human touch, orchestration overhead, instrumentation overhead,
and external waiting remain separate. Evidence is bound to source,
configuration, executable, dependency, task, environment, and result digests.
Failures and infrastructure blocks remain visible. Executing agents cannot
access hidden tests, oracle truth, or evaluator resources.

Raw sensitive interactions may remain access-controlled. Public evidence is
redacted and content-minimized while preserving identity, ordering, timing,
integrity, and outcome verification.

## Human-in-the-loop policy

Human intervention is limited to credentials/permissions, safety or
irreversible actions, predeclared ambiguity escalation, or unrecoverable
infrastructure failure. Each intervention records its trigger, active time,
decision, and effect. Routine progress approvals are prohibited during runs.

## Analysis boundary

The primary unit is the matched ADE × AgentsKit pair. Report each ADE
separately and estimate the within-ADE AgentsKit effect before pooled summaries.
ADE comparisons require uncertainty estimates. Speedup is quality-gated
effective work plus human touch against the task's Senior Engineer Reference
Baseline; external waits are separate.

Official collection remains blocked until all six integrations pass identical
contract, semantic-parity, isolation, cleanup, ledger-completeness,
hidden-evaluation, and reproducibility gates.
