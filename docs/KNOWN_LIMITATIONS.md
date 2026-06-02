# Known Limitations

- The generic fixture validates CLI orchestration with a `passthrough` candidate only.
- Pump and chiller workflows are routed through the new CLI. Cooling-tower and heat-exchanger real runners remain pending.
- Cooling-tower flow reconstruction and heat-exchanger chunked simulation remain in copied legacy scripts.
- Cooling-tower and heat-exchanger archive regression rows remain `blocked` until their normalized new metrics are generated.
- Pump FMU smoke simulation and chiller external-FMU simulations through FMPy are implemented. Cooling-tower and heat-exchanger smoke paths remain pending.
