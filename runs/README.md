# Runs

Each run bundle is identified by an immutable `run_id` and includes its manifest, ledger, artifact index, terminal state, and evaluation references. Public bundles are redacted and hash-linked to private collection records.

Bundles are created only through the controller after the complete condition and
semantic-parity gates pass. The writer creates `ledger.jsonl` before execution,
so a run always has a traceable append-only ledger even when the first event has
not yet been recorded. A blocked gate creates no partial directory and never
invokes an ADE, harness, provider, or task.

After execution, the controller finalizes the bundle exactly once with a
terminal state and normalized artifact references. Finalization appends the
`run.terminal` ledger event; `NOT_APPLICABLE` is reserved for a prepared but
not-yet-executed bundle.
