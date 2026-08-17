# Reproducibility

Every run has a unique `run_id`, immutable manifest, environment snapshot, event log, artifact hashes, configuration hashes, and terminal state.

Durations use monotonic clocks; timestamps use UTC. Prompts and responses are retained privately for audit and published only after redaction when permitted.

Public releases include schemas, scripts, processed datasets, analysis code, dashboard data, and reproducibility instructions. Hidden tests remain private during collection and are released later when safe.

## Local validation

```bash
PYTHONPATH=controller/src python3 -m unittest discover -s controller/tests
PYTHONPATH=controller/src:analysis:. python3 -m unittest discover -s analysis
PYTHONPATH=controller/src:evaluation:. python3 -m unittest discover -s evaluation
node --check dashboard/app.js
python3 analysis/aggregate_runs.py --runs-root runs --tasks-root tasks/public --protocol v1.1 --output /tmp/processed-results-v1.1.json
```

The repository runs the same checks in `.github/workflows/validate.yml`. The
Pages workflow publishes only the dashboard and its public evidence sources;
private paths are excluded by repository policy and `.gitignore`.
