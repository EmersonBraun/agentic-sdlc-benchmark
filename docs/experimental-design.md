# Experimental Design

## Comparison factors

- 3 ADEs: ORCA, Agent Orchestrator, and Compozy
- 3 harnesses: Reference Harness, OpenHands SDK, and mini-SWE-agent
- AgentsKit: ON/OFF
- product type: greenfield/brownfield
- task type: feature, bug/regression, refactoring, and security/operations

The primary matrix contains 18 ADE × harness × AgentsKit conditions.

## Execution modes

- `unattended`: primary mode; no human intervention until a terminal state
- `supervised`: separate secondary mode; every intervention is measured

## Repetition

- pilot: one simple task per condition
- main benchmark: at least five runs per condition
- additional runs are allowed only under a predeclared variance rule
- run order is randomized
- every run starts from a clean worktree and the same commit

## Terminal states

`MERGED`, `FAILED`, `TIMEOUT`, `BUDGET_EXCEEDED`, `HUMAN_REQUIRED`, `INFRASTRUCTURE_FAILURE`, or `INVALID_MEASUREMENT`.

## Freeze rules

Models, prompts, permissions, budgets, timeouts, task set, evaluator, and environment are frozen before the main benchmark release.
