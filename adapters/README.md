# ADE adapters

ADE adapters implement the common lifecycle contract for ORCA, Agent Orchestrator, and Compozy. Compatibility is tested in the pilot and recorded as a result.

The current catalog is declarative. It freezes names, adapter versions, entrypoints, and the no-fallback rule; it does not claim that the external tools are installed. Live integrations must pass the installation and semantic-parity gates before a pilot run can use them.

See [`catalog-v1.0.json`](catalog-v1.0.json) and the controller adapter contract in [`../controller/src/benchmark_controller/adapters.py`](../controller/src/benchmark_controller/adapters.py).
