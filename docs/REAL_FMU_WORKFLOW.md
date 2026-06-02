# Real FMU Workflow

The reusable package already provides:

- FMU `modelDescription.xml` inspection;
- FMI input structured-array construction;
- tunable `start_values` validation;
- deterministic CSV output;
- Modelica template rendering;
- Dymola FMU export invocation;
- external FMU reference recording with SHA256 and FMI interface snapshot;
- grid-search failure isolation;
- continuous-window selection and compressed time mapping.

The real device runners still live in `scripts/legacy_site_a`. Migrating their model-specific simulation calls into the new CLI is the next implementation batch.

External FMUs must remain outside Git and be referenced from YAML.

Supported export modes:

- `disabled`: calibrate and validate without exporting an FMU;
- `external_reference`: validate and record an existing external FMU without copying it;
- `render_and_export`: render Modelica and invoke Dymola locally.

Set `DYMOLA_EXE` and, when required, `BUILDINGS_PACKAGE` in the local
environment. Neither Dymola nor the Buildings Library is distributed with this
repository.
