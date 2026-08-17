# mini-SWE-agent harness adapter

The adapter runs mini-SWE-agent in a pinned Python 3.12 container. The image has no benchmark workspace mounted by default. Read-only preflight uses `mini --help`; task execution remains blocked until the adapter passes workspace, permission, model, ledger, and semantic-parity checks.
