# Known Limitations

- The generic fixture validates CLI orchestration with a `passthrough` candidate only.
- Pump `prepare -> calibrate -> validate -> render -> export -> report` is routed through the new CLI. The other three real-device runners remain pending.
- Cooling-tower flow reconstruction and heat-exchanger chunked simulation remain in copied legacy scripts.
- Chiller, cooling-tower and heat-exchanger archive regression rows remain `blocked` until their normalized new metrics are generated.
- Pump FMU smoke simulation through FMPy is implemented. Other equipment smoke paths remain pending.
