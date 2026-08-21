# Agent Operating Contract

This repository is a controlled SDLC benchmark. The objective is to finish a
valid pilot, not to maximize activity or number of runs.

## Definition of done

The pilot is complete only when all six v1.2 ADE x AgentsKit conditions have
one valid end-to-end run with `MERGED` terminal state, complete append-only
ledger, valid hidden-test evidence, and an independently verified pre-merge
proof. A run that stops before merge is evidence, not completion.

## Hard stops

- Never start another full run while a prior run has an unresolved root cause.
- After two failures with the same root cause, stop execution and isolate it
  with a deterministic local test or fixture before spending more provider
  tokens.
- Never retry a partial run as the same measurement. Create a new run ID and
  preserve the failed bundle.
- Never describe a partial stage as a completed scenario or a useful result
  until its terminal state and evidence are verified.
- Never advance to official collection while any pilot condition lacks a
  valid merge.
- If the controller, ADE, or evaluator is idle without new ledger evidence
  for 10 minutes, diagnose and stop that run; do not wait silently.

## Required loop

1. State the objective, current run, current stage, remaining stages, and exit
   criteria.
2. Run the smallest local check that can falsify the suspected cause.
3. Patch the root cause and add or update one regression check.
4. Run the bounded check and record its result.
5. Only then start one full end-to-end run.
6. Report success, failure, or blocker explicitly. Do not use “next stage” as
   a substitute for a terminal result.

## Budget and retry policy

- One full run per condition at a time.
- At most one rerun after a root-cause patch unless a new, independently
  reproduced failure is found.
- No broad matrix execution during technical debugging.
- Preserve all run bundles and ledgers; never delete evidence to make the
  dashboard or status look healthier.

## Communication contract

Every status report must distinguish:

- attempted runs;
- completed valid runs;
- analysis-eligible runs;
- current blockers;
- exact next action.

Do not claim speedup, quality, ADE, or AgentsKit effects from technical-pilot
data. Technical-pilot bundles are analysis-ineligible by design.
