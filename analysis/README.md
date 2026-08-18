# Analysis

All analysis is generated from append-only raw JSONL and versioned manifests. Scripts must produce processed data, statistical summaries, charts, and dashboard inputs without manual numeric edits.

The deterministic aggregator is [`aggregate_runs.py`](aggregate_runs.py). It
reads run manifests, redacted ledgers, public task baselines, and evaluator
results; calculates effective-work hours, speedup versus the frozen PERT
baseline, quality, success, median, minimum, maximum, IQR, and deterministic
bootstrap confidence intervals. Missing evaluations and invalid runs remain
visible. With no run bundles it emits `status: no-results`, never synthetic
performance numbers.

Run manifests with `analysis_eligible: false` are reported under
`excluded_runs` and are not aggregated. This keeps technical pipeline pilots
separate from the official controlled-study observations.

Example:

```bash
python3 analysis/aggregate_runs.py \
  --runs-root runs \
  --tasks-root tasks/public \
  --protocol v1.1 \
  --output analysis/processed-results-v1.1.json
```

The output contract is [`processed-results-v1.1.schema.json`](processed-results-v1.1.schema.json).
