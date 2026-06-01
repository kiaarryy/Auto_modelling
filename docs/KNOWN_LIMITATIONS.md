# Known Limitations

- The generic fixture validates CLI orchestration with a `passthrough` candidate only.
- Real four-device `prepare -> calibrate -> validate -> report` runs are not yet routed through the new CLI.
- Cooling-tower flow reconstruction and heat-exchanger chunked simulation remain in copied legacy scripts.
- The archive regression command currently emits `blocked` rows until normalized new metrics are generated.
- FMU smoke simulation through FMPy has not yet been executed from the new CLI.
