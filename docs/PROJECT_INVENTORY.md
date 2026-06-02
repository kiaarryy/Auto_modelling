# Project Inventory

## Maintained core

- `src/auto_fmu`: reusable CLI, manifest, optimization, FMU interface inspection, metrics, windows, regression and hygiene checks.
- `adapters/site_a`: building-specific raw-to-canonical entry points kept outside the reusable package.
- `examples/generic_building_minimal`: renamed fixture used for orchestration smoke tests.

## Legacy migration evidence

- `scripts/legacy_site_a`: selected device scripts copied from the external archive.
- `models/pump` and `models/heat_exchanger`: copied Modelica wrappers.
- Real BMS CSVs, generated outputs and FMUs remain external under `${AUTO_FMU_ARCHIVE_ROOT}`.

## Excluded scope

System-level closed-loop scripts, manuscript rewrites, figures and large historical output trees are not copied into this repository.
