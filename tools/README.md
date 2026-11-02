# ASTRA Development and Maintenance Tools

This directory contains standalone maintenance, benchmarking, and repository utilities.

## Available Tools

### 1. `generate_memory_sensitive_benchmark.py`
Generates and cryptographically validates the pre-registered memory-sensitive target benchmark fixture (`experiments/longitudinal/customers.memory-sensitive.json`).

**Usage:**
```bash
PYTHONPATH=src .venv/bin/python tools/generate_memory_sensitive_benchmark.py
```

Validates:
- Catalogue hash against `data/catalogue/catalog.jsonl`
- Oracle feasibility and single-match target uniqueness across all 12 visits
- Partitioning into three scenario groups (memory-helpful, memory-neutral, memory-conflicting)
- Schema version 1 dataset validation via `astra_eval.customers.validate_dataset`
