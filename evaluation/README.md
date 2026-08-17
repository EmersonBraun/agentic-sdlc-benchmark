# Evaluation

Public evaluation contracts and schemas live here. Hidden tests, oracle truth tables, reference solutions, and evaluator prompts are maintained in a private companion repository during collection and released only after the collection tag.

Public evaluator outputs are validated with [`validate_result.py`](validate_result.py) before entering analysis. The validator checks the run identity, bounded scores, boolean hard gates, evaluator state, and hidden-test counts without revealing hidden test names, assertions, or oracle data.

```bash
python3 evaluation/validate_result.py runs/run_example/evaluation-result.json --run-id run_example
```

An evaluator result cannot make a blocked or missing run look complete: the
analysis aggregator keeps missing evaluations and invalid bundles visible.
