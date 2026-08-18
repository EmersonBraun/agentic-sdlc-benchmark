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

### Protocol v1.2 native runner

v1.2 reuses the controller-owned state machine but has a separate state schema
and no harness factor. A clean worktree is verified at the frozen commit before
the ADE starts. Codex planning produces an integrity-bound handoff in the
run-bundle control plane; Grok receives its path and must acknowledge the exact
frozen digest before implementation can complete. AgentsKit ON similarly
materializes public-only context in that non-versionable control plane, runs
each component with the product worktree as its workspace, and requires
planner/executor acknowledgement. OFF rejects any such context as treatment
contamination.

ON evidence passes two distinct seams: the runtime factory records pinned
source, command and output digests, exit status, and exact run workspace, then
a separate controller verifier must validate those observations before the
context is admissible. The concrete native verifier remains a preflight gate;
the generic runner alone does not claim component execution. OFF
also rejects AgentsKit ledger events emitted by the ADE delegate. These
instrumentation files never enter the product tree, so they cannot change the
product diff. Review and completion verification are frozen to the independent
Codex `gpt-5.4-mini` evaluator.

The Compozy implementation uses one local, workspace-bound session per run.
Every prompt carries stable message and idempotency identities, explicitly pins
the role provider/model, validates the returned event stream, and redacts raw
prompt/output content. Model execution is measured as effective work; session
setup and cleanup are recorded separately as orchestration overhead. The
session is stopped after merge or by terminal cleanup.
Compozy currently exposes total context use for Codex but not a complete
input/output/cached/reasoning token and cost breakdown. Technical-pilot records
therefore mark this field unavailable; official collection fails closed until
the concrete executor can observe complete token/cost accounting.

The Agent Orchestrator implementation creates one native, isolated session per
stage: Codex orchestrator sessions for analytical work and Grok worker sessions
for implementation work. Each AO-managed branch is pinned to the preceding
controller-frozen product commit before spawn. Mutating stages must commit and
leave a clean worktree; the controller then fast-forwards to those exact commits in
the measured product worktree so later stages evaluate the produced artifact.
Stable stage sentinels and a semantic completion cache prevent duplicate
completed work across bounded retries. Session creation, inspection, and
cleanup are orchestration overhead. Effective work uses AO's observed
creation-to-last-activity turn interval; remaining spawn wall time is setup
overhead.
Raw output is not published, and every stage receives terminal cleanup.

Checkpoints are not permission to resume a measurement after process failure.
They support bounded retries during one process and idempotent cleanup after a
terminal state. Interrupted measurements remain invalid and are replaced by a
new randomized run ID.

## Harnesses

1. Reference Harness — neutral benchmark control.
2. OpenHands SDK — flexible coding-agent execution layer.
3. mini-SWE-agent — minimal issue-to-code execution layer.

## AgentsKit ablation

The primary comparison is full AgentsKit ON versus OFF. Later ablations isolate doc-bridge, playbook, code-review, and specialized agents.
