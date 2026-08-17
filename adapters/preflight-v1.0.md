# Adapter Preflight v1.0

## Decision

The adapter preflight is **not ready for collection**. No benchmark run was created.

## Current evidence

| Component | Version | Result | Collection decision |
|---|---:|---|---|
| Orca | 1.4.183 | Read-only adapter, account-auth, and workflow-guard probes pass; runtime reachable, graph unavailable, no current worktree | Blocked until graph, workspace binding, and live lifecycle adapter are verified |
| CompozyOS | 0.3.0-beta.16 | Read-only adapter probe passes: daemon/workspace/config/sessions/providers; provider auth summary derived; 0 sessions | Blocked until provider readiness, session lifecycle, and live ledger emission pass |
| Agent Orchestrator | 0.12.6 | Read-only adapter, installed-agent authorization, and spawn-guard ledger probes pass; 4 authorized agents, 0 sessions | Blocked until worker session adapter and live lifecycle emission pass |
| Reference Harness | v1.0 | Contract-ready and tested | Available for local contract tests |
| OpenHands SDK | 1.42.1 | Dependency resolution fails between `lmnr` and OpenTelemetry constraints | Blocked; no dependency override accepted |
| mini-SWE-agent | 2.4.6 | Container image, read-only workspace-boundary, and missing model/auth fail-closed probes pass; network disabled | Blocked until a declared model configuration and full task semantic parity are verified |
| AgentsKit ON | public/local `0.3.0` source | Public core Observer emitted three events into the redacted benchmark ledger; no provider or agent session was used | Blocked until implementation status and full component/runtime integration are verified |
| AgentsKit OFF | v1.0 | Neutral control contract-ready | Available for contract tests |

## Installation provenance

- Compozy package: [`@compozy/cli@0.3.0-beta.16`](https://github.com/compozy/compozy), installed from the npm registry with the recorded integrity value.
- OpenHands SDK: [`software-agent-sdk`](https://github.com/OpenHands/software-agent-sdk), installation guidance from the [official SDK documentation](https://docs.openhands.dev/sdk/getting-started).
- mini-SWE-agent: [`SWE-agent/mini-swe-agent`](https://github.com/SWE-agent/mini-swe-agent), version 2.4.6 in a pinned Python 3.12.10 container.

## Policy

The benchmark does not treat “installed” as “ready”. A component becomes collection-ready only after its adapter exposes the common workspace, tool, permission, context, oracle, Git, GitHub, browser, and ledger semantics. Missing dependencies are recorded as failures; they are not replaced by another factor level.

The machine-local Compozy bootstrap now uses `approve-reads` in its global configuration. This is safer for the host but is not yet a complete benchmark execution policy: any future Compozy run must use an explicit isolated workspace/sandbox policy, record its effective permission mode, and verify provider auth at collection time.

## Executable parity probes

Five side-effect-free probes passed on 2026-08-17. The results and output hashes are recorded in [`probe-results-v1.0.json`](probe-results-v1.0.json), with the probe contract in [`probe-contract-v1.0.json`](probe-contract-v1.0.json). These probes validate executable boundaries and workspace/runtime discovery only; they do not authorize benchmark collection.

The AgentsKit event bridge has a provider-free live probe against the public core Observer. It records bounded metadata and token counts while excluding raw prompts, model content, tool arguments, and tool results. The probe does not call a provider or start an agent session; it validates event delivery and ledger redaction only.

The shared external runtime boundary is contract-tested in [`runtime-contract-v1.0.json`](runtime-contract-v1.0.json). It provides the common argv, permission, workspace, timeout, lifecycle, and ledger semantics. The individual ORCA, Agent Orchestrator, Compozy, OpenHands, and mini-SWE-agent integrations remain not-ready until they are wired to this boundary and pass live semantic-parity checks.

The three ADE adapters now share the normalized lifecycle event contract in [`lifecycle-contract-v1.0.json`](lifecycle-contract-v1.0.json). Live transitions require a ready adapter; blocked transitions are always ledger-visible and raw external payloads are never persisted.

The catalog registry is now wired to the shared boundary: the Reference Harness is executable; all external ADE and non-reference harness entries fail closed until their recorded status becomes `installed-ready`.

The deterministic readiness snapshot is [`readiness-report-v1.0.json`](readiness-report-v1.0.json): 2 of 8 components are ready, but 0 of 18 pilot conditions are ready because every condition includes an external ADE.
