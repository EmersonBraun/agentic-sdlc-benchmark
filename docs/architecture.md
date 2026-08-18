# Architecture

```text
Benchmark Controller
  ├── common contract, ledger, evaluator, and metrics
  ├── persistent condition state machine
  │     ├── bounded in-process retries and crash invalidation
  │     └── controller-owned Git worktree boundary
  ├── ADE adapter
  │     └── native workflows, workers, and linked worktrees
  └── harness adapter
        └── executes agents in isolated workspaces
```

## Responsibilities

- Runtime: executes a model or agent.
- Harness: workspace, tools, local loop, context, and permissions.
- ADE: lifecycle and agent coordination.
- Cockpit: visibility and supervised intervention.
- AgentsKit: doc-bridge, playbook, specialized agents, code review, and memory integration.

## Autonomous execution strategy

The controller continuously advances the next incomplete SDLC step and writes
its state before and after every attempt. Transport retries inside the same
process use a mandatory idempotency key. A process-interrupted official run is
marked `INVALID_MEASUREMENT` and is never resumed; any replacement receives a
new run ID. The selected ADE receives the isolated worktree, branch, task
contract, attempt number, and condition identity and may use its native
workflow and subordinate worktrees inside that boundary.

Only explicit terminal states stop execution: merged, failed, timeout, budget
exceeded, human required, infrastructure failure, or invalid measurement.
Failed worktrees remain available for audit. Successful worktrees are removed
only after an independent verifier confirms every protocol quality gate;
commits and public artifacts remain in the run bundle and Git history.

## Harnesses

1. Reference Harness — neutral benchmark control.
2. OpenHands SDK — flexible coding-agent execution layer.
3. mini-SWE-agent — minimal issue-to-code execution layer.

## AgentsKit ablation

The primary comparison is full AgentsKit ON versus OFF. Later ablations isolate doc-bridge, playbook, code-review, and specialized agents.
