# AUTO_FMU Agent Guide

This project is the curated four-equipment FMU auto-modelling project extracted
from `E:\VISUAL_code\FMU_Modelica`.

## Default Response Language

Respond in Chinese by default unless the user asks for English or a file context
requires English.

## Project Goal

Keep this workspace focused on repeatable auto-modelling for:

- chillers;
- cooling towers;
- pumps;
- heat exchangers.

Avoid reintroducing unrelated manuscript rewrites, historical exploratory
analysis, or broad CT_Model side work unless the user explicitly asks for it.

## Layout Rules

- Core workflow scripts live in `E:\VISUAL_code\AUTO_FMU\scripts`.
- Modelica wrappers live in `E:\VISUAL_code\AUTO_FMU\models`.
- Generated CLI results live in `E:\VISUAL_code\AUTO_FMU\outputs`.
- Real BMS data, historical outputs, and FMUs remain external under
  `E:\VISUAL_code\FMU_Modelica` and are referenced through configuration.
- Selected historical scripts live under `scripts\legacy_site_a` as migration
  evidence. They may still contain archive-specific paths and are not the
  reusable package implementation.

## Safety

- Do not delete source data, FMUs, copied outputs, reports, or compatibility
  folders unless the user gives explicit file-by-file confirmation.
- Do not use recursive delete commands.
- Prefer writing new generated artifacts under `outputs\<device>\...` rather
  than overwriting copied evidence.

## Validation Defaults

Before claiming completion:

- check that expected files exist;
- read generated reports or CSV headers;
- run the smallest relevant script when feasible;
- report any FMU/Dymola/FMPy dependency that prevents rerunning simulations.
- for curation or migration work, verify `README.md`,
  `docs\PROJECT_INVENTORY.md`, `docs\AUTOMODELLING_WORKFLOW.md`, and
  `docs\MIGRATION_MANIFEST.md` all point to existing files and do not contain
  mojibake in user-facing entry titles or paths; use UTF-8 file reads rather
  than terminal rendering alone when checking Chinese filenames;
- keep the migration scope explicit: list copied core workflow assets, reduced
  historical/non-core assets, compatibility paths, and the validation performed.

## Key Docs

- `README.md`
- `docs\PROJECT_INVENTORY.md`
- `docs\AUTOMODELLING_WORKFLOW.md`
- `docs\MIGRATION_MANIFEST.md`
- `docs\REAL_CASE_MIGRATION_MATRIX.md`
- `docs\KNOWN_LIMITATIONS.md`
