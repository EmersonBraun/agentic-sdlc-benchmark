# Decision Log

## D-001 — English repository

All repository code and documentation are written in English.

## D-002 — Primary baseline

Use a Senior Engineer Reference Baseline estimated per task and SDLC stage using three-point estimates and PERT.

## D-003 — Primary speedup

Use quality-gated effective work time; report external waits and total elapsed time separately.

## D-004 — ADE and harness matrix

Compare three ADEs, three harnesses, and AgentsKit ON/OFF.

## D-005 — AgentsKit dogfooding

AgentsKit ecosystem repositories are deferred to a separate dogfood track.

## D-006 — Repository artifacts

MVPs remain in the same repository and are identified by immutable tags associated with run IDs.

## D-007 — External review

No independent reviewer is currently available. This is a documented limitation and future improvement.

## D-008 — Brownfield product

Use Umami as the primary neutral brownfield product. Freeze an immutable upstream snapshot after preflight and preserve attribution and license notices.

## D-009 — Task design

Use four main tasks and two holdouts per product. Main tasks cover feature, bug/regression, refactor, and security/operations. Public issues are intentionally incomplete and each task contains three controlled ambiguities resolved through a deterministic oracle.

## D-010 — Quality and process dimensions

Keep Product Quality Score and SDLC Process Score independent. Product quality controls the primary quality gate; process quality is reported separately.

## D-011 — Hidden evaluation

Keep hidden tests, oracle truth tables, reference solutions, and evaluator resources in a private companion repository during collection. Publish hashes before collection and full artifacts after collection.

## D-012 — Protocol freeze

Freeze approved decisions in `protocol/protocol-v1.0.md`. Any post-freeze change requires a new protocol version and separate cohort.

## D-013 — Public repository identity

The public repository is `agentic-sdlc-benchmark`. Code uses MIT; documentation, schemas, and datasets use CC BY 4.0.

## D-014 — Protocol v1.1 model topology

Create a separate v1.1 cohort with planner `gpt-5.4` and evaluator
`gpt-5.4-mini`; keep all other study factors, tasks, metrics, baseline, hidden
tests, and ledger rules unchanged. The revision is approved because the
provider rejected the v1.0 planner `gpt-5.3-codex` during a controlled ORCA
probe. v1.0 and v1.1 results must never be pooled as if model topology were
unchanged.

## D-015 — Protocol v1.2 factor reduction

Create a separate v1.2 cohort with three ADEs and AgentsKit ON/OFF, yielding
six primary conditions. Remove third-party harnesses as an independent factor;
Codex CLI planning/orchestration and Grok CLI execution are fixed controlled
roles, and their native agent loops may be used. Preserve v1.0/v1.1 as
historical protocols and never pool their observations with v1.2 as though the
factor structure were unchanged.
