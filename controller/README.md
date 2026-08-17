# Benchmark Controller

The controller owns the common benchmark contract, run identity, condition validation, ledger boundaries, and artifact manifests.

The adapter layer now freezes the provider-facing execution plan and fails closed when an external ADE or harness is not installed. It still does not invoke external tools; live integrations are added only after installation and semantic-parity checks pass.

## Local validation

```bash
python -m unittest discover -s controller/tests -p 'test_*.py'
python controller/scripts/validate_conditions.py
```

The adapter contract tests cover all 18 ADE × harness × AgentsKit conditions:

```bash
PYTHONPATH=controller/src python -m unittest discover -s controller/tests -p 'test_*.py'
```
