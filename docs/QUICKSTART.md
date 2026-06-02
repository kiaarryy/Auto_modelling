# Quickstart

Install and run the public fixture:

```powershell
python -m pip install -e ".[test]"
python -m pytest -q
auto-fmu scan-hygiene --root .
auto-fmu validate-config --config examples\generic_building_minimal\project.yaml
auto-fmu batch --config examples\generic_building_minimal\project.yaml --equipment all --run-id generic-smoke
```

Run one configured device:

```powershell
auto-fmu run --config <project.yaml> --equipment <type> --equipment-id <id> --run-id <id>
```

Generated results are written below `outputs\runs\<run-id>`.
