# Data Contracts

Canonical adapter output is UTF-8 CSV with:

- `timestamp`;
- SI-unit numeric columns selected by YAML field mapping;
- provenance in `source_mapping.json`;
- QA in `adapter_qa.csv` and `adapter_qa.md`.

QA covers duplicate timestamps, invalid timestamps, non-finite cells, median interval and per-column missing rate.

Cooling-tower joined-flow reconstruction and heat-exchanger readiness checks remain in the copied legacy scripts until their model-specific adapter stages are migrated.

Each device runner writes:

```text
outputs/runs/<run_id>/<equipment_type>/<equipment_id>/
  prepare/canonical.csv
  prepare/adapter_qa.csv
  readiness.json
  calibrate/all_candidate_metrics.csv
  calibrate/parameters.csv
  selected_model.json
  validate/full_period_metrics.csv
  validate/time_series.csv
  report/summary.md
  manifest.json
```

`modelica/generated_model.mo`, `fmu/exported_model.fmu` or
`fmu/external_fmu_reference.json` are added when the selected export mode
requires them. Generated FMUs remain ignored by Git.

Status priority is `not_ready`, `export_failed`, `accepted`, then `high_error`.
