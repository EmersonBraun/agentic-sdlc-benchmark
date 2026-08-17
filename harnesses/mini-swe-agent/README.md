# mini-SWE-agent harness adapter

The adapter runs mini-SWE-agent in a pinned Python 3.12 container. Read-only
preflight verifies the CLI, a read-only bind mount at `/workspace`, disabled
networking, `approve-reads` parity, the common ledger bridge, and fail-closed
behavior when model/API configuration is absent. Task execution remains
blocked until a declared model configuration, task semantics, and live
collection authorization pass.
