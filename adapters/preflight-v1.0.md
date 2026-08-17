# Adapter Preflight v1.0

## Decision

The adapter preflight is **not ready for collection**. No benchmark run was created.

## Current evidence

| Component | Version | Result | Collection decision |
|---|---:|---|---|
| Orca | 1.4.183 | App/runtime reachable, graph unavailable | Blocked until graph and adapter readiness are verified |
| CompozyOS | 0.3.0-beta.16 | Daemon running; doctor reports provider/extension errors | Blocked until provider auth, permissions, and parity are verified |
| Agent Orchestrator | — | Not installed | Blocked |
| Reference Harness | v1.0 | Contract-ready and tested | Available for local contract tests |
| OpenHands SDK | 1.42.1 | Dependency resolution fails between `lmnr` and OpenTelemetry constraints | Blocked; no dependency override accepted |
| mini-SWE-agent | 2.4.6 | CLI help passes in Python 3.12.10 container | Blocked until semantic parity and model configuration are verified |
| AgentsKit ON | — | Not installed | Blocked |
| AgentsKit OFF | v1.0 | Neutral control contract-ready | Available for contract tests |

## Installation provenance

- Compozy package: [`@compozy/cli@0.3.0-beta.16`](https://github.com/compozy/compozy), installed from the npm registry with the recorded integrity value.
- OpenHands SDK: [`software-agent-sdk`](https://github.com/OpenHands/software-agent-sdk), installation guidance from the [official SDK documentation](https://docs.openhands.dev/sdk/getting-started).
- mini-SWE-agent: [`SWE-agent/mini-swe-agent`](https://github.com/SWE-agent/mini-swe-agent), version 2.4.6 in a pinned Python 3.12.10 container.

## Policy

The benchmark does not treat “installed” as “ready”. A component becomes collection-ready only after its adapter exposes the common workspace, tool, permission, context, oracle, Git, GitHub, browser, and ledger semantics. Missing dependencies are recorded as failures; they are not replaced by another factor level.

The machine-local Compozy bootstrap currently uses `approve-all` in its global configuration. This configuration is not acceptable for benchmark collection and must be replaced or isolated behind the benchmark permission boundary before any Compozy run.

