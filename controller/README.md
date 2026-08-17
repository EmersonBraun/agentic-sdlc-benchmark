# Benchmark Controller

The controller owns the common benchmark contract, run identity, condition validation, ledger boundaries, and artifact manifests.

The adapter layer now freezes the provider-facing execution plan and fails closed when an external ADE or harness is not installed. It still does not invoke external tools; live integrations are added only after installation and semantic-parity checks pass.

The neutral Reference Harness is executable for local argv commands and append-only ledger capture. Its capabilities are explicit and its filesystem boundary rejects path escapes.

Side-effect-free adapter probes are implemented in `benchmark_controller.probes`. Their required groups are frozen in [`../adapters/probe-contract-v1.0.json`](../adapters/probe-contract-v1.0.json).

The public AgentsKit event bridge is implemented in `benchmark_controller.agentskit`. It redacts event content and emits ledger-compatible metadata without starting an agent session.

The shared ADE/harness runtime boundary is implemented in `benchmark_controller.external`. It provides argv-only execution, explicit permission modes, workspace containment, lifecycle events, and ledger redaction for every external adapter.

The registry layers in `benchmark_controller.ade_adapters` and `benchmark_controller.harness_adapters` bind the catalog entries to that boundary. External entries fail closed until their preflight status is `installed-ready`; the Reference Harness is the only executable adapter at this stage.

Deterministic live-readiness evaluation is implemented in `benchmark_controller.readiness` and exposed by `controller/scripts/check_adapter_readiness.py`.

The Agent Orchestrator adapter exposes read-only daemon/project/session preflight and protects `spawn` behind the `installed-ready` gate.

The Compozy adapter exposes read-only daemon/workspace/config/session/provider summaries and protects session creation behind the `installed-ready` gate.

## Local validation

```bash
python -m unittest discover -s controller/tests -p 'test_*.py'
python controller/scripts/validate_conditions.py
```

The adapter contract tests cover all 18 ADE × harness × AgentsKit conditions:

```bash
PYTHONPATH=controller/src python -m unittest discover -s controller/tests -p 'test_*.py'
```

The pilot gate checks every one of the 18 primary conditions and exits non-zero if any required ADE, harness, or AgentsKit factor is not ready:

```bash
PYTHONPATH=controller/src python controller/scripts/check_pilot_gate.py \
  --preflight adapters/preflight-v1.0.json
```
