# Known Limitations

- The generic fixture validates CLI orchestration with a `passthrough` candidate only.
- Pump, chiller, cooling-tower and heat-exchanger workflows are routed through the new CLI.
- Cooling-tower full-period validation is migrated. Window parameter search currently consumes the archived refined-parameter CSV until its search loop is moved into the runner.
- Heat-exchanger Site A regression may consume the archived model-best parameter CSV for historical comparison. Without that CSV, the runner executes its migrated 14-candidate representative-window search.
- Pump FMU smoke simulation and chiller/cooling-tower/heat-exchanger external-FMU simulations through FMPy are implemented.
- HX Dymola wrapper re-export tooling resolves `DYMOLA_EXE` and
  `BUILDINGS_PACKAGE`, but the local Dymola 2025 `/nowindow` invocation stalled
  before producing FMUs during release validation. Existing externally
  exported HX FMUs passed full-period FMPy validation.
