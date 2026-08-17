# Protocol v1.0

Status: frozen planning specification. No collection run may start until the pilot gate passes.

## 1. Study identity

This project is a controlled benchmark study of agentic software delivery across the full software development lifecycle (SDLC).

Primary research question:

> Can an agentic SDLC system deliver software with quality equivalent to or higher than a Senior Engineer Reference Baseline, with lower effective work and lower human intervention?

Primary comparison: quality-gated effective work relative to the estimated Senior Engineer Reference Baseline (SR). Claims must use language such as `X× less effective work relative to the estimated SR baseline`; they must not claim `X× faster than the market`.

## 2. Products

### Greenfield product

A project and activity management application with users, organizations, projects, activities, permissions, event history, and background jobs.

Controlled stack: Next.js, React, TypeScript, PostgreSQL, Prisma, Docker, and GitHub Actions.

### Brownfield product

Umami, selected as the primary neutral brownfield candidate. The benchmark mirror must preserve upstream history, attribution, and license notices. The exact upstream commit, dependency lockfiles, container image digests, and local configuration are frozen after preflight and before the pilot.

Upstream source: https://github.com/umami-software/umami

The AgentsKit ecosystem is not dogfooded in this study. Dogfooding is a future, separate track.

## 3. Experimental factors

The primary matrix is:

| Factor | Levels |
|---|---|
| ADE | ORCA, Agent Orchestrator, Compozy |
| Harness | Reference Harness, OpenHands SDK, mini-SWE-agent |
| AgentsKit | ON, OFF |

This yields 18 conditions. All nine ADE × harness pairs are attempted. Unsupported combinations are recorded as `NOT_APPLICABLE`; they are never silently adapted or removed.

### Execution phases

1. Pilot: one simple full-SDLC task per condition, excluded from primary results.
2. Main matrix: four tasks per product, five repetitions per task-condition combination.
3. Holdout validation: two unseen tasks per product for the selected composition.
4. AgentsKit ablation: OFF, ON complete, and ON without each declared component.

The primary matrix contains 720 target runs:

`2 products × 4 tasks × 18 conditions × 5 repetitions = 720`

The pilot contains 18 runs. Holdout validation contains 20 runs. Ablation contains at most 56 exploratory runs.

## 4. Models and roles

The controlled model topology is fixed:

- Planner and requirements lead: Codex, `gpt-5.3-codex`.
- Executor and fixer: Grok, `grok-4.5`.
- Independent evaluator: `gpt-5.4-mini`.

Exact provider snapshots, request parameters, prompt hashes, request IDs, and pricing tables are recorded in the run manifest. Aliases such as `latest` are prohibited. Temperature is zero and reasoning is high where supported. Native web/X search is disabled.

Roles are not silently substituted. A retry uses the same role and remains within that role's budget.

## 5. Task suite

Each product has four frozen main tasks:

- one small feature task;
- one medium bug/regression task;
- one medium refactoring task;
- one large security/operations task.

Each product also has two holdout tasks: one medium and one large. Holdouts are not used to select the optimized composition.

Task size is based on SR PERT expected effective work:

- Small: 4–8 hours.
- Medium: more than 8 and up to 16 hours.
- Large: more than 16 and up to 32 hours.

The public issue contains realistic product context, problem/opportunity, user goal, known constraints, available evidence, and minimal observable criteria. It is intentionally incomplete. The private task manifest contains canonical requirements, the three seeded ambiguities, oracle truth table, full acceptance criteria, baseline estimates, reference solution, hidden tests, and mutation-test fixtures.

Each task contains exactly three seeded ambiguities:

1. functional;
2. edge-case;
3. technical or operational.

At least one ambiguity affects architecture or acceptance criteria. The oracle allows at most six questions per task, responds deterministically, provides no unsolicited hints, and is shared by all agents in a run.

## 6. Senior Engineer Reference Baseline

The SR is an experienced solo engineer familiar with the stack but not the task solution. The estimate assumes normal IDE features, conventional autocomplete, official documentation, traditional web search, Git, compilers, linters, formatters, and debuggers. It excludes LLMs, copilots, generative autocomplete, AI search, chatbots, agents, and code-generation systems.

The SR baseline is estimated, not measured by a human control execution. Each task and SDLC stage receives minimum, most-likely, and maximum effective-work estimates:

`PERT expected = (minimum + 4 × most_likely + maximum) / 6`

Estimates are frozen before the pilot and are never recalibrated after observing benchmark results. Market sources, dates, units, assumptions, and mappings are published with the baseline.

## 7. Common SDLC contract

Every run follows:

`Issue intake → Requirements discovery → Requirements approval → Technical planning → Task decomposition → Implementation → Local testing → Pull request → CI/QA → Specialized review → Review/fix loop → Final review → Merge → Documentation/memory update`

Required artifacts include a refined PRD, requirements, nonfunctional requirements, acceptance criteria, assumptions, ambiguity log, oracle Q&A, traceability matrix, technical plan, subtasks, risks, ADRs when applicable, test evidence, PR, review findings, fixes, and final documentation.

Requirements and plans are approved automatically by schema validation, oracle checks, and controller gates. No discretionary human approval is allowed in the primary benchmark.

Subtask limits: at most 12 subtasks, maximum depth 2, and a dependency DAG. Commits are coherent, reference task/run IDs, and are never force-pushed, rebased, or squashed. Merge uses a merge commit and preserves all execution commits.

## 8. Conditions and AgentsKit control

The Reference Harness is a neutral benchmark harness, not a presumed winner. It implements the common workspace, tool, permission, context, and ledger contracts. OpenHands SDK and mini-SWE-agent are integrated through adapters.

AgentsKit ON includes doc-bridge, the operational playbook, specialized agents, code-review integration, versioned memory/documentation, and AgentsKit telemetry. AgentsKit OFF uses neutral equivalents with the same roles, prompts, tools, context, limits, and budgets, but no AgentsKit services or code.

Primary AgentsKit ablation is separate from the 18-cell matrix. It includes OFF, ON complete, ON without doc-bridge, ON without playbook, ON without specialized agents, ON without code-review, and ON without AgentsKit-specific memory/telemetry.

## 9. Controlled environment

All controlled conditions use:

- the same model gateway and model snapshots;
- identical prompts, context order, semantic tools, permissions, network allowlist, and budgets;
- fixed ADE, harness, AgentsKit, adapter, dependency, runtime, and container versions;
- identical browser version, `1440×900` viewport, scale factor, locale, and timezone;
- synthetic fixtures, deterministic seeds, ephemeral databases, and isolated workspaces;
- one run at a time on the personal local machine;
- controlled internal reviewer parallelism only when supported by all conditions.

The host inventory records machine model, CPU, cores, RAM, storage, operating system, Docker and runtime versions, connected displays, network, power, thermal state, background load, locale, and timezone. This is contextual evidence and a documented external-validity limitation, not a cross-machine performance claim.

Network allowlist permits the model gateway, the controlled GitHub mirror, package registries, official documentation, and required build services. It blocks private benchmark artifacts, hidden evaluation services, upstream issues/PRs/discussions, search engines, and web/X native search.

## 10. Time, cost, and budgets

`effective_work` includes model inference time, local tool execution, reading, editing, local testing, planning, review, and actions that advance the task. It excludes CI queues, remote CI waiting, human waiting, provider backoff, and other passive external waits. Local tests and builds count as effective work.

The ledger separately records:

- effective work;
- human touch;
- orchestration overhead;
- harness overhead;
- instrumentation overhead;
- external wait;
- total wall time.

Stage effective-work limits equal the SR PERT maximum. Wall and external-wait timeouts are calibrated in the pilot and frozen before collection. Token and cost budgets are calibrated in the pilot and frozen before collection. Exceeding a budget produces `BUDGET_EXCEEDED`.

Cost uses actual tokens and the frozen provider price table in USD. Model, tool, CI, infrastructure, and retry costs are reported separately.

## 11. Human intervention and failures

The primary benchmark has zero discretionary human intervention. The human may not edit code, coach agents, alter prompts, or approve results. Infrastructure recovery is recorded and does not silently continue a partial run.

Terminal states are:

`MERGED`, `FAILED`, `TIMEOUT`, `BUDGET_EXCEEDED`, `HUMAN_REQUIRED`, `INFRASTRUCTURE_FAILURE`, `INVALID_MEASUREMENT`, and `NOT_APPLICABLE`.

Agent errors, timeouts, and budget failures are valid experimental outcomes. Persistent infrastructure faults are invalid for efficacy metrics but remain in the dataset. API transport retries are limited to three attempts with exponential backoff. Invalid reruns receive a new run ID; valid failures are never selectively rerun.

Every run starts from a clean snapshot and new model sessions. Partial runs are never resumed.

## 12. Repository and GitHub isolation

The benchmark uses controlled mirrors for both products. Each run has a unique issue, work branch, integration branch, PR, reviews, merge commit, and final tag. Agents cannot access other runs, upstream issue history, hidden artifacts, or private evaluator resources.

The issue body is immutable after run start. Questions and oracle answers are append-only comments. The issue closes only after merge or remains open with its terminal state documented.

Merge is automatic only after CI, evaluator gates, reviews, documentation, and ledger checks pass. Direct pushes, force-pushes, bypasses, and manual merges are prohibited.

## 13. Quality evaluation

### Product Quality Score

- functional correctness: 40;
- security and authorization: 15;
- regressions: 15;
- tests: 10;
- architecture and maintainability: 10;
- documentation and operations: 5;
- scope discipline: 5.

### SDLC Process Score

- requirements and ambiguities: 20;
- technical planning: 15;
- task decomposition: 10;
- traceability: 15;
- implementation discipline: 10;
- tests and QA: 15;
- review and fixes: 10;
- documentation and memory: 5.

### Quality pass

A run is quality-gated successful only when build, typecheck, CI, mandatory requirements, essential hidden tests, migrations when applicable, security gates, review, documentation, merge, and ledger gates pass; no critical/high issue remains; and Product Quality Score is at least 80/100.

Hidden tests include functional, edge/error, authorization/isolation, security, concurrency/idempotency, regression, cross-layer, performance when relevant, accessibility for relevant UI tasks, and observability when relevant. Hidden tests must kill 100% of critical mutants and at least 80% of non-critical mutants before the pilot.

The independent evaluator receives canonical requirements, the final diff, artifacts, logs, and test results, but not condition metadata. It uses `gpt-5.4-mini` with a fixed rubric and can abstain. Two blind evaluations are run; the median is used. A difference greater than 15 points triggers a third evaluation. Persistent disagreement is documented as abstention.

Reviewers cover functional/architecture, security/authorization, and tests/regressions/operations. Findings use P0–P3 severity, evidence, location, and recommendation. There are at most three review/fix cycles.

## 14. Statistics and selection rules

The primary unit is one complete task-condition execution. Events are not independent samples. Task and product are explicit factors. Report raw data, median, minimum, maximum, IQR, bootstrap confidence intervals, effect sizes, success rate, failures, and stratified results.

Primary causal contrast: AgentsKit ON versus OFF, paired by product, task, ADE, and harness. ADE, harness, and ADE × harness effects are secondary. Multiple comparisons are corrected. The optimized phase is exploratory/confirmatory only under its declared holdout design.

The optimized composition is eligible only with at least 80% quality-gated success on main tasks and no critical security failure. Select among eligible conditions by lowest median effective work plus human touch, then higher process score, lower cost, and lower variability. If none is eligible, optimized validation does not run.

## 15. Pilot gate

The pilot must demonstrate:

- all 18 conditions execute or are classified `NOT_APPLICABLE`;
- complete ledger, timestamps, hashes, and costs;
- issue → PR → review → merge flow;
- correct/defective hidden-test discrimination;
- evaluator calibration and abstention behavior;
- logical reproducibility from a clean snapshot;
- dashboard publication;
- no secret or hidden-artifact leakage;
- documented compatibility and infrastructure failures.

The pilot is not evidence of performance. Any protocol or implementation change discovered during the pilot must be versioned before main collection.

## 16. Data integrity and publication

Raw JSONL is append-only. Structured manifests and results use versioned JSON Schemas. Processed data uses Parquet with CSV exports. Every artifact has a SHA-256 hash and is referenced by a run manifest. Analysis scripts regenerate all derived data and dashboard inputs without manual spreadsheet edits.

Private collection artifacts include full transcripts, hidden tests, oracle, reference solutions, and evaluator resources. Public artifacts include redacted transcripts, hashes, manifests, schemas, processed data, scripts, and dashboard. Hidden content is published only after collection in a new immutable tag.

The public repository is `agentic-sdlc-benchmark`. Code uses MIT. Documentation, schemas, and datasets use CC BY 4.0. Product licenses and upstream notices remain intact.

Public version tags:

`protocol-v1.0`, `pilot-v1.0`, `collection-v1.0`, `results-v1.0`, and `dashboard-v1.0`.

## 17. Validity and claims

The study is a controlled benchmark study, not a peer-reviewed study until independently reviewed. It is conducted by one researcher without an independent human reviewer. The design mitigates this through pre-registration, blind evaluation, automated gates, private hidden artifacts, public redacted data, hashes, and reproducible analysis.

Results must not be generalized beyond the tested products, models, versions, tasks, machine, and protocol. Negative findings, failures, incompatibilities, and limitations are first-class results.
