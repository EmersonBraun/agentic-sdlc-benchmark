# Evaluation Methodology

## Quality gate

An execution is successful only when:

- all hard gates pass;
- all mandatory requirements are satisfied;
- no critical or high unresolved finding remains;
- essential hidden tests pass;
- CI and merge complete;
- `quality_score >= 80/100`.

## Quality score

- functional correctness: 40%
- security and authorization: 15%
- regressions: 15%
- tests: 10%
- architecture and maintainability: 10%
- documentation and operations: 5%
- scope discipline: 5%

Weights and rubric are calibrated on reference and deliberately faulty solutions before the main benchmark.

## Hidden evaluation

Hidden tests are task-specific and common. They cover functional behavior, edge cases, errors, authorization, security, concurrency, idempotency, regressions, cross-layer integration, performance when relevant, and observability when relevant.

Agents receive no hidden-test feedback. The evaluator is blind to ADE, harness, AgentsKit condition, and model identity.

## Statistics

Report raw data, median, minimum, maximum, interquartile range, bootstrap confidence intervals, effect sizes, success rate, and stratified results. Failed runs are never silently removed.
