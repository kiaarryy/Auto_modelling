# Archive Regression

`configs/regression/site_a_archive.yaml` records four initial real baselines.

Run:

```powershell
auto-fmu regression --config configs\regression\site_a_archive.yaml --equipment all --run-id site-a-regression
```

Pump batch runs now write `outputs\runs\<run-id>\new_metrics\pump.csv`
automatically, and the regression command normalizes the archived Pump schema.
The other equipment rows intentionally remain `blocked` until their real
runners write normalized metrics. A real regression is complete only after
matching metric definitions and verifying absolute differences `<= 1e-3`.
