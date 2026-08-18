# Runs

Each run bundle is identified by an immutable `run_id` and includes its manifest, ledger, artifact index, terminal state, and evaluation references. Public bundles are redacted and hash-linked to private collection records.

Bundles are created only through the controller after their explicit gate
passes. Official collection requires the complete condition and global
semantic-parity gates. A preregistered technical pilot may use condition-scoped
readiness, but its manifest must set `analysis_eligible: false`. The writer
creates `ledger.jsonl` before execution, so every attempt remains traceable.

After execution, the controller finalizes the bundle exactly once with a
terminal state and normalized artifact references. Finalization appends the
`run.terminal` ledger event; `NOT_APPLICABLE` is reserved for a prepared but
not-yet-executed bundle. Technical pilots close as `TECHNICAL_PASS` or
`TECHNICAL_FAIL` and never enter official metrics.
