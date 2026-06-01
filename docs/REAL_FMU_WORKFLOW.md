# Real FMU Workflow

The reusable package already provides:

- FMU `modelDescription.xml` inspection;
- FMI input structured-array construction;
- tunable `start_values` validation;
- deterministic CSV output;
- grid-search failure isolation;
- continuous-window selection and compressed time mapping.

The real device runners still live in `scripts/legacy_site_a`. Migrating their model-specific simulation calls into the new CLI is the next implementation batch.

External FMUs must remain outside Git and be referenced from YAML.
