# mini-SWE-agent harness adapter

The adapter runs mini-SWE-agent in a pinned Python 3.12 container. Read-only
preflight verifies the CLI, a read-only bind mount at `/workspace`, disabled
networking, `approve-reads` parity, and the common ledger bridge. Task
execution remains blocked until model configuration, task semantics, and live
collection authorization pass.
