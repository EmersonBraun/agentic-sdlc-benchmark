# Protocol v1.1

Status: approved model-topology revision; collection remains blocked until the
v1.1 readiness gate passes.

## Relationship to v1.0

Protocol v1.1 is a separate cohort. It preserves the v1.0 ADEs, harnesses,
AgentsKit factors, task suite, baseline estimates, metrics, hidden tests,
ledger rules, permissions, network policy, and analysis plan. Existing v1.0
attestations and any future v1.0 results remain historical and are not mixed
with v1.1 results.

## Approved model change

The controlled model topology is now:

- Planner and requirements lead: Codex, `gpt-5.4`.
- Executor and fixer: Grok, `grok-4.5`.
- Independent evaluator: `gpt-5.4-mini`.

The planner changed from `gpt-5.3-codex` because the installed Codex provider
rejected that model for the ChatGPT account. A controlled ORCA probe executed
`gpt-5.4` and returned the bounded worker response contract without modifying
the workspace. Compozy and the Codex CLI also have model-backed `gpt-5.4`
evidence; all remaining ADE, harness, and AgentsKit parity gates are still
required before collection.

No model alias, fallback, or silent substitution is permitted. Every v1.1 run
manifest must record the exact model IDs and provider/runtime snapshots.

## Analysis boundary

The primary v1.1 results must be reported separately from v1.0. Any comparison
between protocol versions is exploratory and must identify the model topology
as a confounder; it is not an ADE, harness, or AgentsKit causal comparison.

## Evidence

The model decision is recorded in
`adapters/model-compatibility-v1.0.json` and the ORCA execution evidence is in
`adapters/orca-session-attestation-v1.0.json`. These files retain their v1.0
schema because they document the historical decision process; v1.1 collection
must create v1.1 run manifests and attestations.
