# Data Contracts

Canonical adapter output is UTF-8 CSV with:

- `timestamp`;
- SI-unit numeric columns selected by YAML field mapping;
- provenance in `source_mapping.json`;
- QA in `adapter_qa.csv` and `adapter_qa.md`.

QA covers duplicate timestamps, invalid timestamps, non-finite cells, median interval and per-column missing rate.

Cooling-tower joined-flow reconstruction and heat-exchanger readiness checks remain in the copied legacy scripts until their model-specific adapter stages are migrated.
