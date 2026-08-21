# Pilot Exit Criteria

The technical pilot is not complete when the controller starts all six
conditions. It is complete only when the evidence table below has six rows and
each row points to a valid merged run bundle.

| Condition | Required evidence |
| --- | --- |
| ORCA + AgentsKit OFF | `MERGED`, ledger, hidden tests, independent proof |
| ORCA + AgentsKit ON | `MERGED`, ledger, hidden tests, independent proof |
| Agent Orchestrator + AgentsKit OFF | `MERGED`, ledger, hidden tests, independent proof |
| Agent Orchestrator + AgentsKit ON | `MERGED`, ledger, hidden tests, independent proof |
| Compozy + AgentsKit OFF | `MERGED`, ledger, hidden tests, independent proof |
| Compozy + AgentsKit ON | `MERGED`, ledger, hidden tests, independent proof |

Attempts and failed bundles remain in the ledger but do not count as completed
conditions. Official collection remains blocked until this table is complete
and semantic parity is rechecked.
