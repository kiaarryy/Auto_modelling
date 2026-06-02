# Result Interpretation

Each device writes `readiness.json`, validation metrics, `report\summary.md`
and `manifest.json`.

Status priority is:

1. `not_ready`: source data is insufficient.
2. `export_failed`: export, FMU inspection or simulation failed.
3. `accepted`: validation completed within configured thresholds.
4. `high_error`: validation completed but at least one metric exceeded a threshold.

Heat-exchanger manifests also report passed and failed validation chunks.
Failed chunks are written to CSV and are never silently discarded.
