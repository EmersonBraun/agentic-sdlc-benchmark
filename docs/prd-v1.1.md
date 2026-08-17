# PRD: Controlled Agentic SDLC Benchmark v1.1

## Problem

Teams want to use AI to deliver more software, but speed claims are difficult
to compare when requirements, repositories, tools, quality gates, and human
interventions differ. This study provides a public, reproducible protocol for
measuring how agentic development environments affect the complete SDLC.

## Goal

Run the same frozen tasks through a controlled 18-condition matrix:

- ADEs: ORCA, Agent Orchestrator, and Compozy.
- Harnesses: Reference Harness, OpenHands SDK, and mini-SWE-agent.
- AgentsKit: OFF and ON.

Compare quality-gated effective work against the Senior Engineer Reference
Baseline, while preserving a complete redacted action ledger and independent
hidden-test evaluation.

## Scope

The protocol covers issue intake, requirements discovery, ambiguity handling,
planning, decomposition, implementation, local testing, pull request, CI/QA,
specialized review, fix loops, final review, merge, and documentation. The
pilot uses one frozen greenfield task per condition. The main benchmark may
expand the task set only after the pilot protocol and measurement pipeline are
validated.

## Acceptance criteria

1. Every condition uses the same task, seed policy, budgets, SDLC contract, and
   measurement definitions.
2. Every run is bound to an immutable task-manifest hash and base commit.
3. Every in-scope action is represented in an append-only, redacted ledger.
4. Quality is evaluated through private oracle data and hidden tests unavailable
   to the executing agent.
5. Speedup uses effective work plus human touch time and excludes external CI
   waiting from the work numerator.
6. Failed, incomplete, invalid, and infrastructure-blocked runs remain visible
   in the analysis rather than being silently removed.
7. Public artifacts include the protocol, schemas, redacted evidence, analysis
   code, processed data, dashboard, limitations, and reproducibility commands.

## Non-goals

- Publishing private prompts, model responses, credentials, hidden tests, or
  unreleased oracle truth tables before the release policy permits it.
- Claiming that results generalize beyond the evaluated tasks, models,
  repositories, and environment.
- Using the private `agentskit-os` package in the public study.

## Decision record

This PRD is the public study contract. Changes after collection starts require
an explicit protocol version and must not rewrite v1.1 observations.
