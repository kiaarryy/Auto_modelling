# Configuration

Configuration is YAML. It supports `extends`, `${ENVIRONMENT_VARIABLE}`
expansion and ignored `configs\**\*.local.yaml` overrides.

The public Site A template is `configs\site_a\project.example.yaml`. Keep real
BMS paths, external FMU paths and machine-specific tool paths outside Git:

```powershell
$env:AUTO_FMU_ARCHIVE_ROOT = "<external-archive-root>"
$env:AUTO_FMU_SITE_A_ROOT = "<external-site-data-root>"
```

Each device may define readiness thresholds, model candidates and an export
mode: `disabled`, `external_reference` or `render_and_export`.
