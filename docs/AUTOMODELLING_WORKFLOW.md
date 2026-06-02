# Auto-Modelling Workflow

Install the local CLI:

```powershell
python -m pip install -e . --no-deps
```

Run the renamed fixture:

```powershell
auto-fmu validate-config --config examples\generic_building_minimal\project.yaml
auto-fmu batch --config examples\generic_building_minimal\project.yaml --equipment all --run-id generic-smoke
auto-fmu scan-hygiene --root .
```

The fixture uses a `passthrough` candidate and tests orchestration only. It is not a real FMU calibration.

Run one configured device:

```powershell
auto-fmu run --config <project.yaml> --equipment <type> --equipment-id <id> --run-id <id>
```

The legacy `prepare`, `calibrate`, `validate` and `report` commands remain
available for compatibility with the initial fixture workflow.

Generate the current archive-regression readiness report:

```powershell
$env:AUTO_FMU_ARCHIVE_ROOT = "<external-archive-root>"
auto-fmu regression --config configs\regression\site_a_archive.yaml --equipment all --run-id site-a-regression
```
