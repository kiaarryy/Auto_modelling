# AUTO_FMU

`AUTO_FMU` is a curated reusable four-equipment FMU auto-modelling workspace:

- chillers;
- cooling towers;
- pumps;
- heat exchangers.

The repository keeps reusable code and compact migration evidence. Real BMS
data, historical output trees and FMUs remain external and are referenced by
ignored local configuration or environment variables.

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
auto-fmu batch --config examples\generic_building_minimal\project.yaml --equipment all --run-id generic-smoke
auto-fmu scan-hygiene --root .
```

The renamed fixture uses a `passthrough` candidate to test orchestration. It is
not a real FMU calibration.

Run one configured device with:

```powershell
auto-fmu run --config <project.yaml> --equipment pump --equipment-id <id> --run-id <id>
```

The public Site A template uses environment variables and contains all 17 Pump
mappings plus chiller, cooling-tower and heat-exchanger real-case entries:

```powershell
$env:AUTO_FMU_ARCHIVE_ROOT = "<external-archive-root>"
$env:AUTO_FMU_SITE_A_ROOT = "<external-site-data-root>"
auto-fmu batch --config configs\site_a\project.example.yaml --equipment pump --run-id site-a-pump-batch
auto-fmu run --config configs\site_a\project.example.yaml --equipment chiller --equipment-id DCCP_01 --run-id site-a-chiller
auto-fmu batch --config configs\site_a\project.example.yaml --equipment cooling_tower --run-id site-a-ct-batch
auto-fmu batch --config configs\site_a\project.example.yaml --equipment heat_exchanger --run-id site-a-hx-batch
auto-fmu batch --config configs\site_a\project.example.yaml --equipment all --run-id site-a-batch
```

## Archive Regression Readiness

```powershell
$env:AUTO_FMU_ARCHIVE_ROOT = "<external-archive-root>"
auto-fmu regression --config configs\regression\site_a_archive.yaml --equipment all --run-id site-a-regression
```

The regression command converts archived device-specific CSVs into one schema
and checks absolute metric differences against the configured tolerance.

## Optional Export Toolchain

Dymola and the Modelica Buildings Library are optional external tools. They are
not distributed with this repository. Existing FMUs may be referenced through
ignored local configuration for validation-only runs.

## Start Here

1. `docs\PROJECT_INVENTORY.md`
2. `docs\MIGRATION_MANIFEST.md`
3. `docs\REAL_CASE_MIGRATION_MATRIX.md`
4. `docs\AUTOMODELLING_WORKFLOW.md`
5. `docs\KNOWN_LIMITATIONS.md`
6. `docs\SITE_A_VALIDATION_REPORT.md`
