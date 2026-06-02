# Export Toolchain

FMU export is optional. Validation may use an existing external FMU reference;
the runner records its path, SHA256, interface snapshot and smoke result
without copying the FMU.

For local Dymola export, configure:

```powershell
$env:DYMOLA_EXE = "<path-to-Dymola.exe>"
$env:BUILDINGS_PACKAGE = "<path-to-Buildings-package.mo>"
```

Dymola and the Modelica Buildings Library are external dependencies and are
not distributed in this repository. Generated `*.fmu` files remain ignored.
