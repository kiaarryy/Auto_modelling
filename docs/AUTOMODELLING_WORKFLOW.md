# Auto-Modelling Workflow

Install the local CLI:

```powershell
python -m pip install -e . --no-deps
```

Run the renamed fixture:

```powershell
auto-fmu validate-config --config examples\generic_building_minimal\project.yaml
auto-fmu prepare --config examples\generic_building_minimal\project.yaml --equipment all --run-id generic-smoke
auto-fmu calibrate --config examples\generic_building_minimal\project.yaml --equipment all --run-id generic-smoke
auto-fmu validate --config examples\generic_building_minimal\project.yaml --equipment all --run-id generic-smoke
auto-fmu report --config examples\generic_building_minimal\project.yaml --equipment all --run-id generic-smoke
auto-fmu scan-hygiene --root .
```

The fixture uses a `passthrough` candidate and tests orchestration only. It is not a real FMU calibration.

Generate the current archive-regression readiness report:

```powershell
auto-fmu regression --config configs\regression\site_a_archive.yaml --equipment all --run-id site-a-regression
```
