# ADR-006: Blind independent evaluation for protocol v1.2

**Status:** Accepted
**Date:** 2026-08-19

## Context

The v1.2 evaluator must judge the product without learning the ADE or AgentsKit
assignment. It must not trust an agent to certify hidden tests, CI, or ledger
integrity, and an ADE-produced quality score must never become the canonical
study score. Repository instructions, global skills, plugins, branch names,
worktree paths, and condition-bearing run identifiers are potential treatment
leaks.

## Decision

Evaluation is a controller-owned pipeline with four boundaries:

1. **Evidence collector.** The controller executes hidden tests and validates
   CI, ledger, and artifact integrity outside the measured agent worktree. It
   emits a schema-validated redacted attestation bound to the task manifest and
   product commit. The attestation contains no condition, ADE, AgentsKit, model,
   branch, or original path.
2. **Blind snapshot.** The evaluator receives a clean committed archive under a
   random opaque directory. Repository instruction surfaces (`AGENTS.md`,
   `CLAUDE.md`, `.agents`, `.codex`, and equivalent nested files) and benchmark
   runtime-control files are excluded. The snapshot manifest records exclusions
   and source commit without exposing treatment identity to the model.
3. **Neutral Codex process.** Codex runs read-only and ephemeral with plugins,
   apps, skill discovery, remote plugins, and multi-agent features disabled.
   The controller records the frozen command and effective capability inventory.
4. **Consensus and composition.** Two blind `gpt-5.4-mini` evaluations use the
   frozen rubric. Their median is canonical. A score spread above 15 triggers a
   third evaluation; persistent disagreement or missing evidence yields
   `abstain`. Controller-owned hard gates are composed only after model output
   validation. The resulting independent score replaces, rather than validates,
   any ADE-produced score.

The completion verifier returns a canonical proof to the condition runner. The
runner persists that proof as the sole publishable quality result.

## Alternatives considered

1. **Evaluate directly in the measured worktree.** Rejected because path,
   branch, and repository instructions reveal or influence the treatment.
2. **Let the model claim hidden-test and ledger gates.** Rejected because those
   artifacts are outside its admissible evidence boundary.
3. **Require exact equality with the ADE score.** Rejected because it preserves
   ADE control over the published score and treats normal evaluator variance as
   failure.
4. **Use one evaluator pass.** Rejected because the frozen methodology requires
   two blind passes and a third on disagreement.

## Consequences

- Evaluation costs and latency increase, but are measured separately from
  development effective work.
- A condition cannot pass until the controller-owned hidden-test and ledger
  attestations exist and validate.
- Raw hidden tests, prompts, model replies, and treatment identifiers remain
  private; public outputs contain only hashes, bounded counts, scores, and gates.
- The same evaluator pipeline is used for all six conditions without fallback.

