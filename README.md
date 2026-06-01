# AUTO_FMU

`E:\VISUAL_code\AUTO_FMU` is the curated migration workspace for reusable
four-equipment FMU auto-modelling:

- chillers;
- cooling towers;
- pumps;
- heat exchangers.

The repository keeps reusable code and compact migration evidence. Real Site A
BMS data, historical output trees and FMUs remain external under
`E:\VISUAL_code\FMU_Modelica` and are referenced by configuration.

## Layout

```text
adapters\site_a\                 Building-specific raw-to-canonical adapters
configs\adapters\site_a\         Initial real-case field mappings
configs\regression\              Archive regression readiness configuration
docs\                            Migration inventory, workflow and limitations
examples\generic_building_minimal Renamed non-Site-A orchestration fixture
models\                          Copied pump and heat-exchanger wrappers
scripts\legacy_site_a\           Selected archived real workflow scripts
src\auto_fmu\                    Reusable CLI core
tests\                           Focused unit and smoke tests
```

## Install

```powershell
python -m pip install -e . --no-deps
```

## Generic Smoke

```powershell
auto-fmu validate-config --config examples\generic_building_minimal\project.yaml
auto-fmu prepare --config examples\generic_building_minimal\project.yaml --equipment all --run-id generic-smoke
auto-fmu calibrate --config examples\generic_building_minimal\project.yaml --equipment all --run-id generic-smoke
auto-fmu validate --config examples\generic_building_minimal\project.yaml --equipment all --run-id generic-smoke
auto-fmu report --config examples\generic_building_minimal\project.yaml --equipment all --run-id generic-smoke
auto-fmu scan-hygiene --root .
```

The renamed fixture uses a `passthrough` candidate to test orchestration. It is
not a real FMU calibration.

## Archive Regression Readiness

```powershell
auto-fmu regression --config configs\regression\site_a_archive.yaml --equipment all --run-id site-a-regression
```

The current report is expected to mark cases as `blocked` until the real
model-specific runners generate normalized new metric CSVs.

## Start Here

1. `docs\PROJECT_INVENTORY.md`
2. `docs\MIGRATION_MANIFEST.md`
3. `docs\REAL_CASE_MIGRATION_MATRIX.md`
4. `docs\AUTOMODELLING_WORKFLOW.md`
5. `docs\KNOWN_LIMITATIONS.md`
