# Adapter Preflight v1.1

## Decision

The v1.1 cohort is approved as a separate model-topology cohort, but it is
**not ready for benchmark collection**. Four conditions are component-complete,
but the global gate remains closed until **18 of 18** are ready. No official
benchmark run or performance result exists.

## Model policy

The frozen v1.1 roles are planner/requirements lead `gpt-5.4`, executor/fixer
`grok-4.5`, and independent evaluator `gpt-5.4-mini`. The policy is recorded in
[`../protocol/model-policy-v1.1.json`](../protocol/model-policy-v1.1.json).
Evidence from v1.0 and v1.1 is never mixed.

## Current component state

| Component | Status | What is verified | What remains |
|---|---|---|---|
| ORCA 1.4.184 | installed-not-ready | Runtime, graph, workspace, three supervised `gpt-5.4` executions, cleanup, and release | Runtime rejected every authoritative `worker_done` with `dispatch_capability_invalid`; lifecycle settlement is unverified |
| Agent Orchestrator 0.12.6 | installed-not-ready | Isolated spawn, polling, termination, cleanup, and redacted ledger bridge | `gpt-5.4` execution and native event treatment are unverified |
| Compozy 0.3.0-beta.16 | installed-ready | Exact `gpt-5.4` provider-bound prompt, isolated workspace cleanup, and redacted event-to-ledger bridge | Component ready; global 18-condition semantic parity remains a separate protocol gate |
| Reference Harness | contract-ready | Common argv, workspace, permissions, and ledger contract | External ADE readiness still gates every primary condition |
| OpenHands SDK | dependency-resolution-failed | Normal resolver failure is reproduced for tested versions | Upstream-compatible dependency graph |
| mini-SWE-agent 2.4.6 | installed-ready | Grok `grok-4.5` through native CLI/OAuth, mini-SWE-controlled tools, append-only ledger, greenfield and Umami product tests, submission, source integrity, session cleanup, and container cleanup | Reliability is measured during repetitions; no readiness blocker remains |
| AgentsKit OFF | contract-ready | Neutral control contract | None at the contract level |
| AgentsKit ON | installed-ready | Pinned public source, live redacted ledger, native Doc Bridge/Playbook/Code Review, and a provider-backed matched ON/OFF task | Benefit estimation remains an official-replication outcome behind the global gate |

## Evidence

- [Preflight machine record](preflight-v1.1.json)
- [Host machine inventory](machine-inventory-v1.1.json)
- [Condition readiness snapshot](condition-readiness-v1.1.json)
- [v1.1 blocker register](blocker-register-v1.1.json)
- [ORCA lifecycle probe](orca-v1.1-lifecycle-probe-attestation.json)
- [Latest ORCA lifecycle probe](orca-v1.1-lifecycle-probe-attestation-2.json)
- [Latest ORCA bootstrap diagnostic](orca-v1.1-lifecycle-probe-attestation-3.json)
- [Latest ORCA Dispatch-capability diagnostic](orca-v1.1-lifecycle-probe-attestation-4.json)
- [Agent Orchestrator session probe](agent-orchestrator-v1.1-session-probe-attestation.json)
- [Compozy session probe](compozy-v1.1-session-probe-attestation.json)
- [Latest Compozy availability probe](compozy-v1.1-availability-probe-attestation-2.json)
- [Compozy provider/lifecycle bridge probe](compozy-v1.1-session-probe-attestation.json)
- [mini-SWE boundary probe](mini-swe-v1.1-preflight-attestation.json)
- [mini-SWE native CLI bridge and cross-product task probes](mini-swe-cli-bridge-attestation-v1.1.json)
- [AgentsKit pinned preflight](agentskit-v1.1-preflight-attestation.json)
- [AgentsKit component readiness](agentskit-v1.1-component-readiness-attestation.json)
- [Deterministic execution-readiness report](execution-readiness-v1.1.json)
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
