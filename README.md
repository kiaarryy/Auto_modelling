# AUTO_FMU

`E:\VISUAL_code\AUTO_FMU` is a curated standalone copy of the core FMU/Modelica
auto-modelling work originally developed under
`E:\VISUAL_code\FMU_Modelica`.

The project focuses on four equipment types:

- Chiller: ElectricEIR, ElectricReformulatedEIR, and Carnot_TEva screening.
- Cooling tower: Site A Merkel/YorkCalc FMU calibration and full-period validation.
- Pump: Site A empirical and MBL speed/system pump modelling.
- Heat exchanger: Site A Buildings-based HX FMU calibration and validation.

## Project Layout

```text
E:\VISUAL_code\AUTO_FMU
|-- scripts\                 Core reproducible workflow scripts.
|-- models\                  Pump, heat-exchanger, and system Modelica wrappers.
|-- configs\                 Site A topology and System IR configs.
|-- data\                    Organized source-data archive.
|-- CT_Model\DATA\Site_A\    Compatibility copy for scripts expecting old paths.
|-- Cali_EIR_BSU_CH1\        Compatibility copy for chiller and CT FMU scripts.
|-- outputs\                 Curated metrics, reports, FMUs, figures, and time series.
|-- docs\                    New project docs plus copied source reports.
```

The root `CT_Model` and `Cali_EIR_BSU_CH1` folders are intentionally retained as
compatibility paths because the original scripts compute paths from the project
root. The organized copies under `data\` are kept for readability and archival
traceability.

For the same reason, chiller outputs are available both under the organized
`outputs\chiller\...` view and under the original default script paths such as
`outputs\electric_eir` and `outputs\comparison`.

## Start Here

Read these files first:

1. `docs\项目总览与自动建模流程.md`
2. `docs\PROJECT_INVENTORY.md`
3. `docs\AUTOMODELLING_WORKFLOW.md`
4. `docs\MIGRATION_MANIFEST.md`

Install the Python dependencies from this project root:

```powershell
python -m pip install -r requirements.txt
```

Many full-period FMU runs are expensive. For review or writing, prefer reading
the existing outputs first. For focused regeneration, run the device-specific
commands in `docs\AUTOMODELLING_WORKFLOW.md`.

## Current Status Snapshot

| Equipment | Scope | Current evidence |
| --- | --- | --- |
| Chiller | Multi-site/multi-circuit curve screening for EIR, EEIR, Carnot_TEva | `outputs\chiller\comparison\three_type\table4_recalculated.csv`, `table5_recalculated.csv`, `table6_recalculated.csv` |
| Cooling tower | 7 Site A towers, full-period validation | `outputs\cooling_tower\auto_model_site_a_full_period\site_a_full_period_summary.md` |
| Pump | 15 Site A pumps, full-period power validation | `outputs\pump\auto_model_site_a\site_a_pump_auto_model_report.md` |
| Heat exchanger | HX_01 and HX_02 FMU validation, HX_03 blocked by missing fields | `outputs\heat_exchanger\site_a_hx_auto_modelling_report.md` |

## Important Limitations

- Some copied scripts still contain explanatory text mentioning
  `E:\VISUAL_code\FMU_Modelica`; runnable paths are now satisfied inside
  `E:\VISUAL_code\AUTO_FMU` through compatibility folders.
- The old full `CT_Model` project was not copied because it is about 12.6 GB and
  contains many non-core analyses. This project keeps the Site A data and the
  auto-modelling outputs needed by the four-device workflow.
- Cooling tower TIFF manuscript figures were not copied. The compact PNG/SVG/PDF
  versions are preserved under `outputs\cooling_tower\figures`.
