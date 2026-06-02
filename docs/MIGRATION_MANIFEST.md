# Migration Manifest

## Copied core assets

- 31 selected legacy device workflow scripts under `scripts/legacy_site_a`.
- 2 pump and 2 heat-exchanger Modelica wrappers under `models`.

## External assets

- Site A BMS data: `${AUTO_FMU_ARCHIVE_ROOT}\CT_Model\DATA\Site_A`.
- Chiller data and FMUs: `${AUTO_FMU_ARCHIVE_ROOT}\Cali_EIR_BSU_CH1`.
- Historical metrics: `${AUTO_FMU_ARCHIVE_ROOT}\outputs`.

No FMU, real BMS CSV or historical output tree is copied into Git.

## Reduced assets

System closed-loop scripts, manuscript-generation code and historical exploratory analyses remain in the archive.

## Validation

- Public CI runs pytest, hygiene scanning, generic config validation and the generic fixture batch.
- Local Site A release validation runs all 28 configured devices with explicit statuses.
- Local archive regression normalizes all four equipment schemas and checks 19 metrics at tolerance `<= 1e-3`.
