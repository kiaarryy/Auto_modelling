from __future__ import annotations

from pathlib import Path

from scripts.legacy_site_a.export_site_a_hx_fmus import dymola_interface_egg, export_with_dymola_interface


class FakeDymola:
    def __init__(self) -> None:
        self.calls = []
        self.closed = False

    def ExecuteCommand(self, command: str):
        self.calls.append(("ExecuteCommand", command))
        return True

    def openModel(self, path: str, changeDirectory: bool = False):
        self.calls.append(("openModel", path, changeDirectory))
        return True

    def translateModelFMU(self, model: str, store_result: bool, model_name: str, **kwargs):
        self.calls.append(("translateModelFMU", model, store_result, model_name, kwargs))
        return model_name

    def getLastError(self):
        return ["", 0, 0, 0]

    def close(self) -> None:
        self.closed = True


def test_hx_dymola_interface_egg_is_resolved_from_installation(tmp_path: Path) -> None:
    installation = tmp_path / "dymola2025"
    exe = installation / "bin64" / "Dymola.exe"

    assert dymola_interface_egg(exe) == installation / "Modelica" / "Library" / "python_interface" / "dymola.egg"


def test_hx_interface_export_translates_both_wrappers_and_closes(tmp_path: Path) -> None:
    fake = FakeDymola()
    wrappers = [(tmp_path / "A.mo", "A"), (tmp_path / "B.mo", "B")]

    result = export_with_dymola_interface(
        out_dir=tmp_path,
        buildings_package=tmp_path / "Buildings" / "package.mo",
        wrappers=wrappers,
        dymola_exe=Path("E:/APP/dymola2025/bin64/Dymola.exe"),
        interface_factory=lambda **_: fake,
    )

    assert result.returncode == 0
    assert [call[1] for call in fake.calls if call[0] == "translateModelFMU"] == ["A", "B"]
    assert fake.closed
