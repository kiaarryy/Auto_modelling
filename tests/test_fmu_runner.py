from __future__ import annotations

from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

import numpy as np
import pytest

from auto_fmu.fmu.inspect import inspect_fmu
from auto_fmu.fmu.runner import build_fmi_input, validate_start_values, write_deterministic_csv


MODEL_DESCRIPTION = """<?xml version="1.0" encoding="UTF-8"?>
<fmiModelDescription fmiVersion="2.0" modelName="Mock" guid="mock">
  <ModelVariables>
    <ScalarVariable name="u" valueReference="1" causality="input" variability="continuous">
      <Real />
    </ScalarVariable>
    <ScalarVariable name="y" valueReference="2" causality="output" variability="continuous">
      <Real />
    </ScalarVariable>
    <ScalarVariable name="gain" valueReference="3" causality="parameter" variability="tunable">
      <Real start="1.0" />
    </ScalarVariable>
    <ScalarVariable name="compiled" valueReference="4" causality="parameter" variability="fixed">
      <Real start="2.0" />
    </ScalarVariable>
  </ModelVariables>
</fmiModelDescription>
"""


def mock_fmu(path: Path) -> Path:
    with ZipFile(path, "w", ZIP_DEFLATED) as archive:
        archive.writestr("modelDescription.xml", MODEL_DESCRIPTION)
    return path


def test_inspect_fmu_lists_interface_and_tunable_parameters(tmp_path: Path) -> None:
    snapshot = inspect_fmu(mock_fmu(tmp_path / "mock.fmu"))

    assert snapshot.inputs == ("u",)
    assert snapshot.outputs == ("y",)
    assert snapshot.tunable_parameters == ("gain",)
    assert snapshot.variables["compiled"].variability == "fixed"


def test_validate_start_values_rejects_unexposed_parameter(tmp_path: Path) -> None:
    snapshot = inspect_fmu(mock_fmu(tmp_path / "mock.fmu"))

    with pytest.raises(ValueError, match="not tunable"):
        validate_start_values(snapshot, {"compiled": 4.0})


def test_validate_start_values_can_allow_fixed_initialization_parameter(tmp_path: Path) -> None:
    snapshot = inspect_fmu(mock_fmu(tmp_path / "mock.fmu"))

    validate_start_values(snapshot, {"compiled": 4.0}, allow_fixed_parameters=True)


def test_build_input_and_csv_output_are_deterministic(tmp_path: Path) -> None:
    values = build_fmi_input({"time": [0, 300], "u": [1.0, 2.0]}, ["u"])
    output = tmp_path / "output.csv"
    write_deterministic_csv(output, values)

    assert values.dtype.names == ("time", "u")
    assert np.allclose(values["time"], [0.0, 300.0])
    assert output.read_text(encoding="utf-8") == "time,u\n0,1\n300,2\n"
