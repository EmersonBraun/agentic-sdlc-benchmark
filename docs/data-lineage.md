# Data Lineage and Ledger Policy

The benchmark distinguishes readiness evidence from collected-run evidence.

## Readiness evidence

Adapter attestations under `adapters/` are immutable, redacted records of
installation probes, lifecycle probes, model compatibility, and boundary
checks. They explain why a condition is ready or blocked. They are not task
results and must not be included as benchmark performance observations.

## Collected-run evidence

After the selected v1.1 gate passes, the controller creates one directory per
run under `runs/<run_id>/`. The immutable `manifest.json` binds the run to the
protocol, condition, task-manifest SHA-256, model/component snapshots, seed,
environment, budgets, and terminal state. `ledger.jsonl` is append-only and
records every in-scope SDLC action with stage, actor, tool, status, duration,
time category, artifact references, and redacted payload hash.

Technical-pilot bundles are preregistered pipeline validations. Their manifests
set `gate_mode: technical-pilot` and `analysis_eligible: false`; the aggregator
reports them as excluded and never mixes them with official observations. The
official collection still requires the complete 18-condition readiness gate.

The public ledger never contains credentials, raw prompts, model responses,
unredacted tool arguments, or private hidden-test data. Those remain in the
private audit store until the release policy permits publication.

## Current status

The repository contains five immutable technical-pilot bundles for the
preregistered Compozy × Reference Harness × AgentsKit OFF condition. Attempts
recorded integration discoveries as the acceptance criteria were strengthened;
the fifth passed model execution, lifecycle normalization, fixture integrity,
and residual-state cleanup. Every attempt sets `analysis_eligible: false`.
There are still no official observations or performance results, and the
official 18/18 gate remains unchanged.

Use `controller/scripts/prepare_run_bundle.py` to create a bound bundle and
`controller/scripts/validate_run_bundle.py` to verify its public integrity.
