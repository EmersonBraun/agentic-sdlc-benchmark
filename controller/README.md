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

The ORCA adapter exposes redacted runtime, command-schema, and current-worktree probes and protects workflow creation behind the `installed-ready` gate. Unrelated local ORCA state is never persisted into benchmark evidence.

The mini-SWE-agent adapter uses a pinned container with `--network none`, read-only root filesystem, no workspace mount during preflight, and a temporary HOME. Task execution remains protected by the `installed-ready` gate.

## Local validation

```bash
python -m unittest discover -s controller/tests -p 'test_*.py'
python controller/scripts/validate_conditions.py
```

The adapter contract tests cover all 18 ADE × harness × AgentsKit conditions:

```bash
PYTHONPATH=controller/src python -m unittest discover -s controller/tests -p 'test_*.py'
```

The official collection gate checks every one of the 18 primary conditions and exits non-zero if any required ADE, harness, or AgentsKit factor is not ready:

```bash
PYTHONPATH=controller/src python controller/scripts/check_pilot_gate.py \
  --preflight adapters/preflight-v1.0.json
```

Condition-scoped technical readiness is reported separately:

```bash
PYTHONPATH=controller/src python controller/scripts/check_pilot_gate.py \
  --preflight adapters/preflight-v1.1.json \
  --gate-mode technical-pilot
```

The conditioned executor has two explicit modes. `official-collection` requires the complete 18/18 gate and global semantic parity. `technical-pilot` accepts only preregistered, condition-scoped readiness evidence and marks every bundle as ineligible for official analysis. Neither mode permits fallback resolution.

```python
from benchmark_controller.pilot_executor import ConditionedPilotExecutor

prepared = ConditionedPilotExecutor(
    preflight,
    gate_mode="technical-pilot",
).prepare_condition(
    run_id="run_example",
    ade="compozy",
    harness="reference",
    agentskit="off",
)
```

Once the selected gate and semantic-parity evidence are verified, [`benchmark_controller.run_bundles.RunBundleWriter`](src/benchmark_controller/run_bundles.py) validates the frozen task manifest and creates the immutable run directory with `manifest.json`, an append-only `ledger.jsonl`, `artifact-index.json`, and `evaluation-refs.json`. It records the task-manifest SHA-256 and gate mode before touching the output root. Technical-pilot bundles carry `analysis_eligible: false`; the official v1.1 collection remains blocked until the full matrix passes.

The operational entrypoints are `scripts/prepare_run_bundle.py` and
`scripts/validate_run_bundle.py`. The former is fail-closed and creates no
directory while the readiness gate is blocked; the latter validates run
identity, task-manifest binding, ledger sequence, and public event fields.

`scripts/plan_pilot_matrix.py` emits the seeded 18-condition schedule without
starting collection. The schedule is the handoff consumed by the eventual
live executor after the complete readiness gate passes. The
`benchmark_controller.collection.PilotCollectionCoordinator` then requires a
real ADE/harness/AgentsKit backend, finalizes every outcome, and converts
backend exceptions into `INFRASTRUCTURE_FAILURE`; it never substitutes a fake
executor.
