# Limitations and Threats to Validity

- The Senior Engineer Reference Baseline is estimated, not measured from human executions.
- The study is conducted by one researcher without an independent pre-publication reviewer.
- Results are constrained by one personal local machine and its hardware, operating system, network, thermal state, and background workload.
- The captured host currently uses Node 25/pnpm 10 locally while product CI uses Node 22/pnpm 11; this runtime distinction is recorded rather than silently pooled.
- Model behavior and provider availability may change across releases.
- The selected products, tasks, and repositories may not represent all software engineering work.
- Hidden tests reduce solution leakage but do not eliminate model pretraining contamination.
- Qualitative adjudication may contain researcher bias.

Mitigations include protocol freezing, blind evaluation, external hidden tests, immutable ledgers, reproducible analysis, complete run publication, and a future independent audit.
