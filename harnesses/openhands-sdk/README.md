# OpenHands SDK harness adapter

The adapter uses a clean Python 3.12 container with the OpenHands SDK pinned to
one version. Dependency resolution must succeed without `--no-deps` or
constraint overrides before the harness can become collection-ready. The
tools and workspace packages remain out of scope until their dependency graph
resolves cleanly in the same pinned environment.

## Preflight result

As of 2026-08-17, the normal resolver fails for all SDK versions tested here
(`1.42.1`, `1.40.1`, and `1.29.3`). The conflict is between `lmnr`'s pinned
`opentelemetry-semantic-conventions==0.60b1` requirement and the available
`opentelemetry-instrumentation` releases. This harness is therefore recorded
as `dependency-resolution-failed`; no session adapter is exposed and no
benchmark task may use it until the upstream dependency graph resolves.
