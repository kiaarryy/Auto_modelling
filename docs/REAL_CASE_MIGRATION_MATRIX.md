# Real Case Migration Matrix

| Equipment | Baseline | Legacy script | Legacy metric | External FMU | New CLI status |
| --- | --- | --- | --- | --- | --- |
| Pump | `CDWP_03` | `scripts/legacy_site_a/calibrate_site_a_pump_empirical_model.py` | `${AUTO_FMU_ARCHIVE_ROOT}\outputs\pump\auto_model_site_a\full_period_validation_metrics.csv` | `PumpEmpiricalPower.mo` exported locally with Dymola | real CLI implemented; `CDWP_03` regression difference `0`; 17-device batch writes explicit statuses |
| Chiller | `DCCP_01` / archive `CH_01` | `scripts/legacy_site_a/run_multi_chiller_eir.py` | `${AUTO_FMU_ARCHIVE_ROOT}\outputs\comparison\three_type\table4_recalculated.csv` | EIR, EEIR and Carnot wrappers referenced externally | real CLI implemented; three candidate differences `< 3e-14`; EEIR selected |
| Cooling tower | `CT_03` | `scripts/legacy_site_a/calibrate_site_a_ct_fmus.py` | `${AUTO_FMU_ARCHIVE_ROOT}\outputs\cooling_tower\auto_model_site_a_full_period\site_a_full_period_metrics_long.csv` | `${AUTO_FMU_ARCHIVE_ROOT}\Cali_EIR_BSU_CH1\Modelica\CTM_0FMU.fmu` | basic adapter template added; joined-flow reconstruction pending |
| Heat exchanger | `HX_02` | `scripts/legacy_site_a/calibrate_site_a_hx_fmus.py` | `${AUTO_FMU_ARCHIVE_ROOT}\outputs\heat_exchanger\validation\site_a_hx_full_period_metrics.csv` | archive `outputs\heat_exchanger\modelica_interface\fmu` | basic adapter template added; chunked CLI simulation pending |

Boundary cases retained for readiness reporting: `HXCWP_03` and `HX_03`.
