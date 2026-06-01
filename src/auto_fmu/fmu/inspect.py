from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Dict, Tuple
from xml.etree import ElementTree
from zipfile import ZipFile


@dataclass(frozen=True)
class FMUVariable:
    name: str
    causality: str
    variability: str
    value_reference: str


@dataclass(frozen=True)
class FMUInterfaceSnapshot:
    fmu_path: str
    variables: Dict[str, FMUVariable]

    @property
    def inputs(self) -> Tuple[str, ...]:
        return tuple(variable.name for variable in self.variables.values() if variable.causality == "input")

    @property
    def outputs(self) -> Tuple[str, ...]:
        return tuple(variable.name for variable in self.variables.values() if variable.causality == "output")

    @property
    def tunable_parameters(self) -> Tuple[str, ...]:
        return tuple(
            variable.name
            for variable in self.variables.values()
            if variable.causality == "parameter" and variable.variability == "tunable"
        )

    def to_dict(self) -> dict[str, object]:
        return {"fmu_path": self.fmu_path, "variables": {name: asdict(variable) for name, variable in self.variables.items()}}


def inspect_fmu(path: Path) -> FMUInterfaceSnapshot:
    path = Path(path).resolve()
    with ZipFile(path) as archive:
        root = ElementTree.fromstring(archive.read("modelDescription.xml"))
    variables = {}
    for node in root.findall("./ModelVariables/ScalarVariable"):
        variable = FMUVariable(
            name=node.attrib["name"],
            causality=node.attrib.get("causality", "local"),
            variability=node.attrib.get("variability", "continuous"),
            value_reference=node.attrib.get("valueReference", ""),
        )
        variables[variable.name] = variable
    return FMUInterfaceSnapshot(fmu_path=str(path), variables=variables)
