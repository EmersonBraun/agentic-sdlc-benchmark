# Operator Readiness Runbook v1.1

This runbook closes the remaining pilot gates after local, provider-free
preflight. It is intentionally fail-closed: a component is not collection-ready
until its fresh attestation satisfies the blocker register and the 18-condition
gate reports ready.

## Non-negotiable controls

- Use only public, open-source components declared in `catalog-v1.1.json`.
- Do not use, import, or expose `agentskit-os`.
- Use isolated profiles, workspaces, and temporary sessions for every probe.
- Do not place credentials, raw prompts, model content, tool arguments, or tool
  results in the repository ledger.
- For the historical v1.1 cohort, keep the protocol models unchanged: planner
  `gpt-5.3-codex`, evaluator `gpt-5.4-mini`. The separately approved v1.1
  cohort uses [`../protocol/model-policy-v1.1.json`](../protocol/model-policy-v1.1.json)
  and must be run against [`preflight-v1.1.json`](preflight-v1.1.json). Never
  mix v1.1 and v1.1 evidence; a model substitution requires a recorded
  protocol revision and is not an operational workaround.
- Do not weaken dependency resolution, permissions, workspace boundaries, or
  network policy to make a gate pass.

## Gate sequence

Run the gates in this order for the final release decision. Independent,
preparation-only probes may proceed after an earlier failure when they cannot
contaminate a task, disclose hidden material, or create an official run. Always
preserve the redacted failure evidence.

| Order | Gate | Operator action | Passing evidence |
|---:|---|---|---|
| 1 | ORCA workspace and graph | Register the isolated benchmark workspace and expose a ready graph through the approved ORCA runtime path. | Workspace binding, graph reachability, normalized lifecycle events, cleanup, and no session leakage. |
| 2 | Agent Orchestrator semantics | Review the polling bridge against the shared lifecycle contract and run one approved isolated worker session. | Spawn, polling transitions, ledger events, cleanup, and zero cross-run state leakage; the lack of native events is explicitly accepted or remains a blocker. |
| 3 | Compozy provider/model | Closed for v1.1; recheck only after a version, provider, model-policy, or adapter change. | [`compozy-v1.1-component-readiness-attestation.json`](compozy-v1.1-component-readiness-attestation.json) remains hash-consistent with exact-model, lifecycle, ledger, and cleanup evidence. |
| 4 | OpenHands resolver | Closed for v1.1 using the officially documented `uv` resolver; recheck after package, resolver, or image changes. | Exact SDK, tools, workspace, and agent-server versions resolve without `--no-deps` or overrides, followed by workspace, permission, ledger, integrity, and cleanup probes. |
| 5 | mini-SWE-agent model boundary | Closed for v1.1; recheck after bridge, image, model, or task-contract changes. | Native Grok CLI/OAuth execution, frozen image identity, independent product tests, lifecycle, cleanup, and ledger parity pass. |
| 6 | AgentsKit ON parity | Closed for component-local v1.1 readiness; preserve the pinned public source and matched OFF treatment. | Public components map to the ledger, the provider-backed task passes, OFF contains zero AgentsKit events, and no private component is used. |
| 7 | Global semantic parity | Regenerate the matrix only after every component-local gate is ready. | All seven invariants pass for 18/18 conditions; this gate is not attributed to any individual ADE. |

## Evidence procedure

For each gate:

1. Record the operator, timestamp, component version, runtime/image digest,
   workspace/session identifiers as hashes, and the exact probe command.
2. Capture only redacted summaries and SHA-256 hashes in a versioned attestation.
3. Run the relevant read-only probe and the shared semantic-parity tests.
4. Update the blocker register, preflight record, and deterministic readiness
   snapshots for the active protocol cohort together.
5. Run the validation suite and commit the evidence before attempting the next
   gate.

## Final release gate

The pilot may start only when all of the following are true:

```text
check_pilot_gate.can_start == true
ready_conditions == 18
semantic_parity.status == ready
blocker_register.status == clear
```

If any condition is false, the pilot executor must return a blocked plan and
create no benchmark run or external session.

## Current state

As of 2026-08-18, Compozy, Agent Orchestrator, OpenHands SDK, mini-SWE-agent,
the reference harness, and both AgentsKit treatments are independently ready.
Twelve component-complete v1.1 conditions are ready, but the global 18/18 collection gate remains
blocked. Its reference-harness ON/OFF technical pair remains excluded from
official analysis. ORCA executes `gpt-5.4` but rejects authoritative lifecycle
settlement; Agent Orchestrator relies on bounded read-only datastore observation because its public CLI lacks native events;
OpenHands 1.42.1 is ready through the pinned `uv` container bridge. mini-SWE-agent is ready through the
authenticated Grok CLI/OAuth transport; no API key is part of the protocol.
The remaining gates are upstream or protocol-owned, not operator credentials.
