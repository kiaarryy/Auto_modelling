# Archive Regression

`configs/regression/site_a_archive.yaml` records four initial real baselines.

Run:

```powershell
auto-fmu regression --config configs\regression\site_a_archive.yaml --equipment all --run-id site-a-regression
```

Until new normalized metric CSVs exist under `outputs\runs\site-a-regression\new_metrics`, the report intentionally records `blocked` rows. A real regression is complete only after matching metric definitions and verifying absolute differences `<= 1e-3`.
