# Benchmark Controller

The controller owns the common benchmark contract, run identity, condition validation, ledger boundaries, and artifact manifests.

This first scaffold intentionally has no provider, GitHub, ADE, harness, or model integration. Those integrations are added only after contract tests pass.

## Local validation

```bash
python -m unittest discover -s controller/tests -p 'test_*.py'
python controller/scripts/validate_conditions.py
```
