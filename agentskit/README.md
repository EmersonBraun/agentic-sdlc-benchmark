# AgentsKit integrations

This directory contains the public AgentsKit ON integration and matched OFF control. Component ablations are separate from the primary 18-condition matrix.

[`config-v1.0.json`](config-v1.0.json) freezes the ON components, neutral OFF counterparts, and ablation names. The ON integration is not considered live until installation, version, event, redaction, and parity evidence is attached to a pilot manifest.

The controller bridge consumes the public AgentsKit `AgentEvent` observer contract and writes only bounded metadata plus token counts to the benchmark ledger. Raw prompts, model output, tool arguments, and tool results are never persisted. See [`event-contract-v1.0.json`](event-contract-v1.0.json) and [`../controller/src/benchmark_controller/agentskit.py`](../controller/src/benchmark_controller/agentskit.py).
