# Archive Regression

`configs/regression/site_a_archive.yaml` records four initial real baselines.

Run:

```powershell
auto-fmu regression --config configs\regression\site_a_archive.yaml --equipment all --run-id site-a-regression
```

Each real batch writes `outputs\runs\<run-id>\new_metrics\<equipment>.csv`.
The regression command normalizes the four archived schemas before comparing
them. A real regression is complete only after matching metric definitions and
verifying absolute differences `<= 1e-3`.
