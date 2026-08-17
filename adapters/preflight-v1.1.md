# Adapter Preflight v1.1

## Decision

The v1.1 cohort is approved as a separate model-topology cohort, but it is
**not ready for benchmark collection**. The deterministic gate reports **0 of
18 conditions ready**. No benchmark run or performance result exists.

## Model policy

The frozen v1.1 roles are planner/requirements lead `gpt-5.4`, executor/fixer
`grok-4.5`, and independent evaluator `gpt-5.4-mini`. The policy is recorded in
[`../protocol/model-policy-v1.1.json`](../protocol/model-policy-v1.1.json).
Evidence from v1.0 and v1.1 is never mixed.

## Current component state

| Component | Status | What is verified | What remains |
|---|---|---|---|
| ORCA 1.4.184 | installed-not-ready | Runtime, graph, workspace, and candidate `gpt-5.4` launch | Worker stalled during MCP bootstrap; normalized lifecycle parity is unverified |
| Agent Orchestrator 0.12.6 | installed-not-ready | Isolated spawn, polling, termination, cleanup, and redacted ledger bridge | `gpt-5.4` execution and native event treatment are unverified |
| Compozy 0.3.0-beta.16 | unavailable-in-current-shell | Historical local workspace/session creation and cleanup; candidate model connectivity | Executable is not available in the current shell; provider-bound `gpt-5.4` session and lifecycle ledger bridge must be revalidated |
| Reference Harness | contract-ready | Common argv, workspace, permissions, and ledger contract | External ADE readiness still gates every primary condition |
| OpenHands SDK | dependency-resolution-failed | Normal resolver failure is reproduced for tested versions | Upstream-compatible dependency graph |
| mini-SWE-agent 2.4.6 | installed-not-ready | Isolated image, read-only workspace, network boundary, and CLI startup | Non-production model/auth boundary and task parity |
| AgentsKit OFF | contract-ready | Neutral control contract | None at the contract level |
| AgentsKit ON | installed-not-ready | Pinned public source, core bridge, redaction, integrated fixture, and offline component checks | Model-backed task parity with all declared components and matched OFF |

## Evidence

- [Preflight machine record](preflight-v1.1.json)
- [Host machine inventory](machine-inventory-v1.1.json)
- [Condition readiness snapshot](condition-readiness-v1.1.json)
- [v1.1 blocker register](blocker-register-v1.1.json)
- [ORCA lifecycle probe](orca-v1.1-lifecycle-probe-attestation.json)
- [Latest ORCA lifecycle probe](orca-v1.1-lifecycle-probe-attestation-2.json)
- [Agent Orchestrator session probe](agent-orchestrator-v1.1-session-probe-attestation.json)
- [Compozy session probe](compozy-v1.1-session-probe-attestation.json)
- [Latest Compozy availability probe](compozy-v1.1-availability-probe-attestation-2.json)
- [mini-SWE boundary probe](mini-swe-v1.1-preflight-attestation.json)
- [AgentsKit pinned preflight](agentskit-v1.1-preflight-attestation.json)
- [Private evaluation companion](https://github.com/EmersonBraun/agentic-sdlc-benchmark-private) (access-controlled; manifest hash is recorded in the preflight JSON)

All public evidence is redacted. It records bounded metadata, hashes, state
transitions, and token counts where available; it does not publish credentials,
raw prompts, model responses, tool arguments, or tool results.

## Release gate

Collection may start only when all of the following are true:

```text
ready_conditions == 18
check_pilot_gate.can_start == true
semantic_parity.status == verified
no fallback resolution was used
```

Until then, the controller must create no run bundle and invoke no benchmark
task. Provider authentication, upstream dependency changes, or a new model
choice require explicit external setup or a new protocol decision.
