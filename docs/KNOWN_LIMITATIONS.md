# Known Limitations

- The generic fixture validates CLI orchestration with a `passthrough` candidate only.
- Pump, chiller and cooling-tower workflows are routed through the new CLI. Heat-exchanger real routing remains pending.
- Cooling-tower full-period validation is migrated. Window parameter search currently consumes the archived refined-parameter CSV until its search loop is moved into the runner.
- Heat-exchanger archive regression rows remain `blocked` until normalized new metrics are generated.
- Pump FMU smoke simulation and chiller/cooling-tower external-FMU simulations through FMPy are implemented. Heat-exchanger smoke remains pending.
