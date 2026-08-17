# Agentic SDLC Benchmark

An open, controlled study of autonomous software delivery across the full SDLC.

The benchmark compares ADEs, harnesses, model coordination policies, and AgentsKit-enabled workflows against a Senior Engineer Reference Baseline.

## Status

`protocol-v1.0` is frozen as the historical cohort. `protocol-v1.1` is the approved separate model-topology cohort (`gpt-5.4` planner, `gpt-5.4-mini` evaluator). No benchmark runs have started.

## Repository map

- `docs/` — research protocol, methodology, architecture, limitations, and publishing rules
- `protocol/` — frozen protocol versions and operational manifests
- `protocol/` — frozen experiment configurations
- `schemas/` — versioned data contracts
- `tasks/` — benchmark issues and task metadata
- `products/` — greenfield and brownfield fixtures
- `harnesses/` — harness adapters and configurations
- `adapters/` — ADE adapters
- `agentskit/` — AgentsKit integrations and ablations
- `evaluation/` — public and private evaluation components
- `analysis/` — processing, statistics, charts, and content inputs
- `dashboard/` — static public dashboard
- `runs/` — immutable run bundles and manifests

The public dashboard is published at `/dashboard/` by
[`.github/workflows/pages.yml`](.github/workflows/pages.yml) after the
validation workflow passes. It currently reports readiness and evidence, not
performance results; the dashboard will only show measured outcomes after
versioned run bundles and evaluator records exist.

## Research question

Can an agentic SDLC system deliver production-quality software with less effective work than a Senior Engineer Reference Baseline, while preserving reliability and reducing human intervention?

## Important constraint

The repository is intentionally English-only. Conversations about the study may be conducted in Portuguese.
