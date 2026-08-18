#!/usr/bin/env python3
"""Validate the frozen protocol condition matrix without external dependencies."""

from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "controller" / "src"))

from benchmark_controller.conditions import load_conditions  # noqa: E402


if __name__ == "__main__":
    document = load_conditions(ROOT / "protocol" / "conditions-v1.2.json")
    print(f"valid: protocol={document['protocol_version']} conditions={len(document['conditions'])}")
