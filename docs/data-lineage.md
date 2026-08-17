# Data Lineage and Ledger Policy

The benchmark distinguishes readiness evidence from collected-run evidence.

## Readiness evidence

Adapter attestations under `adapters/` are immutable, redacted records of
installation probes, lifecycle probes, model compatibility, and boundary
checks. They explain why a condition is ready or blocked. They are not task
results and must not be included as benchmark performance observations.

## Collected-run evidence

After the complete v1.1 gate passes, the controller creates one directory per
run under `runs/<run_id>/`. The immutable `manifest.json` binds the run to the
protocol, condition, task-manifest SHA-256, model/component snapshots, seed,
environment, budgets, and terminal state. `ledger.jsonl` is append-only and
records every in-scope SDLC action with stage, actor, tool, status, duration,
time category, artifact references, and redacted payload hash.

The public ledger never contains credentials, raw prompts, model responses,
unredacted tool arguments, or private hidden-test data. Those remain in the
private audit store until the release policy permits publication.

## Current status

The repository currently contains no collected run bundles. Therefore there is
no fabricated action ledger and no performance result. The bundle writer and
validator are ready, and the writer intentionally creates nothing while the
18-condition gate is blocked. Running the preparation command is the first
observable collection event only after readiness is verified.

Use `controller/scripts/prepare_run_bundle.py` to create a bound bundle and
`controller/scripts/validate_run_bundle.py` to verify its public integrity.
