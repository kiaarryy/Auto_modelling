# Site A Validation Report

This report is intentionally sanitized. It includes public equipment IDs,
statuses and regression outcomes only. It does not include BMS records, full
time series, FMUs or machine-specific paths.

## Pump

- 17 devices executed.
- 15 devices: `accepted`.
- `CHWP_05`: `not_ready` because no qualifying modelling window was available.
- `HXCWP_03`: `not_ready`; historical flow p95 is about `2.80 kg/s`, below the configured `10 kg/s` readiness threshold.
- `CDWP_03` archived CVRMSE absolute difference: `0`.

## Chiller

- Public validation case: `DCCP_01`.
- Candidates: `ElectricEIR`, `ElectricReformulatedEIR`, `Carnot_TEva`.
- Selected candidate: `ElectricReformulatedEIR`.
- Three-candidate archived metric differences pass tolerance `<= 1e-3`;
  maximum absolute difference is about `3.13e-13`.

## Cooling Tower

- `CT_01..CT_07` executed with an explicit status for every device.
- `CT_01`: `high_error`.
- `CT_02..CT_07`: `accepted`.
- `CT_03` Merkel `TOut`, `Q` and `P` archived CVRMSE differences: `0`.

## Heat Exchanger

- `HX_01`: `accepted`; 172 validation chunks, 0 failed.
- `HX_02`: `accepted`; 202 validation chunks, 0 failed.
- `HX_03`: `not_ready` because both-side temperature fields are unavailable.
- `HX_02` two-candidate, six-metric archived CVRMSE maximum absolute difference: `0`.

## Release Batch

`auto-fmu batch --equipment all --run-id site-a-batch` wrote an explicit
status for all 28 configured devices. Unified archive regression checked 19
metrics: 1 Pump, 9 Chiller, 3 Cooling Tower and 6 Heat Exchanger metrics. All
19 passed tolerance `<= 1e-3`.
