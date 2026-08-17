# Architecture

```text
Benchmark Controller
  ├── common contract, ledger, evaluator, and metrics
  ├── ADE adapter
  │     └── orchestrates lifecycle and coordination
  └── harness adapter
        └── executes agents in isolated workspaces
```

## Responsibilities

- Runtime: executes a model or agent.
- Harness: workspace, tools, local loop, context, and permissions.
- ADE: lifecycle and agent coordination.
- Cockpit: visibility and supervised intervention.
- AgentsKit: doc-bridge, playbook, specialized agents, code review, and memory integration.

## Harnesses

1. Reference Harness — neutral benchmark control.
2. OpenHands SDK — flexible coding-agent execution layer.
3. mini-SWE-agent — minimal issue-to-code execution layer.

## AgentsKit ablation

The primary comparison is full AgentsKit ON versus OFF. Later ablations isolate doc-bridge, playbook, code-review, and specialized agents.
