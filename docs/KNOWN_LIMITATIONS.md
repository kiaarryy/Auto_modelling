# Known Limitations

- The generic fixture validates CLI orchestration with a `passthrough` candidate only.
- Pump, chiller, cooling-tower and heat-exchanger workflows are routed through the new CLI.
- Cooling-tower window search and full-period validation are migrated. An
  explicit local `parameter_csv` override remains supported for historical
  regression audits.
- Heat-exchanger Site A regression may consume the archived model-best parameter CSV for historical comparison. Without that CSV, the runner executes its migrated 14-candidate representative-window search.
- Pump FMU smoke simulation and chiller/cooling-tower/heat-exchanger external-FMU simulations through FMPy are implemented.
- HX Dymola wrapper re-export resolves `DYMOLA_EXE` and `BUILDINGS_PACKAGE`
  and uses the bundled Dymola Python interface. Both wrappers were re-exported
  locally and passed one-hour FMPy smoke validation. The legacy `/nowindow`
  MOS path remains available through `--batch` for audit use.
