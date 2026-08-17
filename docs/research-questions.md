# Research Questions and Hypotheses

## Primary research question

Can an agentic SDLC system deliver software with quality equivalent to or higher than a Senior Engineer Reference Baseline, with lower effective work time and lower human intervention?

## Primary outcome

Quality-gated effective speedup:

```text
Senior Engineer Reference Baseline estimated effective work
/
agent effective work + human touch time
```

Only runs that satisfy the quality gate are included in the speedup view. Reliability is always reported separately across all runs.

## Hypotheses

1. Agentic systems can complete selected SDLC tasks while satisfying the quality gate.
2. The best ADE/harness stack will reduce effective work relative to the reference baseline.
3. AgentsKit reduces human intervention, regressions, and run-to-run variance without reducing quality.
4. A composed framework can combine strengths from multiple ADEs and harnesses.

## Scope of claims

Claims are limited to the evaluated tasks, repositories, models, protocol version, and environment release.
