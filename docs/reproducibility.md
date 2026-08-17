# Reproducibility

Every run has a unique `run_id`, immutable manifest, environment snapshot, event log, artifact hashes, configuration hashes, and terminal state.

Durations use monotonic clocks; timestamps use UTC. Prompts and responses are retained privately for audit and published only after redaction when permitted.

Public releases include schemas, scripts, processed datasets, analysis code, dashboard data, and reproducibility instructions. Hidden tests remain private during collection and are released later when safe.
