"""Create Dymola export scripts for Site A heat exchanger FMU wrappers.

By default this script only writes the `.mos` file and export guide. Use
`--run` to invoke Dymola from the command line after reviewing the generated
script.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping, Sequence


ROOT = Path(__file__).resolve().parents[2]
BUILDINGS_PACKAGE = Path(os.environ.get("BUILDINGS_PACKAGE", r"E:\APP\dymola2025\Modelica\Buildings 12.1.0\package.mo"))
MODEL_DIR = ROOT / "models" / "heat_exchanger"
PLATE_SOURCE = MODEL_DIR / "SiteAHXPlateEffectivenessNTU.mo"
CONSTANT_SOURCE = MODEL_DIR / "SiteAHXConstantEffectiveness.mo"
OUT_DIR = ROOT / "outputs" / "heat_exchanger" / "modelica_interface" / "fmu"
PLATE_MODEL = "SiteAHXPlateEffectivenessNTU"
CONSTANT_MODEL = "SiteAHXConstantEffectiveness"


@dataclass(frozen=True)
class InterfaceExportResult:
    returncode: int
    stdout: str
    stderr: str


def as_modelica_path(path: Path) -> str:
    return str(path.resolve()).replace("\\", "/")


def default_dymola_exe(env: Mapping[str, str] | None = None) -> Path:
    env = env or os.environ
    for key in ["DYMOLA_EXE", "DYMOLA_PATH"]:
        if env.get(key):
            return Path(str(env[key]))
    found = shutil.which("Dymola.exe") or shutil.which("dymola.exe")
    if found:
        return Path(found)
    candidate = Path(r"E:\APP\dymola2025\bin64\Dymola.exe")
    return candidate if candidate.exists() else Path("Dymola.exe")


def build_export_mos(
    out_dir: Path = OUT_DIR,
    buildings_package: Path = BUILDINGS_PACKAGE,
    plate_source: Path = PLATE_SOURCE,
    constant_source: Path = CONSTANT_SOURCE,
) -> str:
    return "\n".join(
        [
            f'cd("{as_modelica_path(out_dir)}");',
            f'openModel("{as_modelica_path(buildings_package)}", changeDirectory=false);',
            f'openModel("{as_modelica_path(plate_source)}", changeDirectory=false);',
            f'openModel("{as_modelica_path(constant_source)}", changeDirectory=false);',
            'Advanced.FMI.AllowStringParameters=true;',
            f'translateModelFMU("{PLATE_MODEL}", false, "{PLATE_MODEL}", fmiVersion="2", fmiType="cs");',
            "getLastError();",
            f'translateModelFMU("{CONSTANT_MODEL}", false, "{CONSTANT_MODEL}", fmiVersion="2", fmiType="cs");',
            "getLastError();",
            "exit();",
            "",
        ]
    )


def write_export_mos(out_dir: Path = OUT_DIR) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    mos_path = out_dir / "export_site_a_hx_fmus.mos"
    with mos_path.open("w", encoding="utf-8", newline="\n") as f:
        f.write(build_export_mos(out_dir=out_dir))
    return mos_path


def write_export_guide(mos_path: Path, out_dir: Path = OUT_DIR) -> Path:
    guide_path = out_dir / "export_site_a_hx_fmus_guide.md"
    text = "\n".join(
        [
            "# Site A Heat Exchanger FMU Export Guide",
            "",
            f"- Dymola script: `{mos_path}`",
            f"- Output directory: `{out_dir}`",
            f"- Buildings package: `{BUILDINGS_PACKAGE}`",
            f"- Plate wrapper: `{PLATE_SOURCE}`",
            f"- Constant effectiveness wrapper: `{CONSTANT_SOURCE}`",
            "",
            "## GUI Steps",
            "",
            "1. Open Dymola.",
            "2. Load `E:/APP/dymola2025/Modelica/Buildings 12.1.0/package.mo`.",
            "3. Load both wrapper `.mo` files under `models/heat_exchanger`.",
            "4. Run `export_site_a_hx_fmus.mos`, or export each model manually as FMI 2.0 Co-Simulation.",
            "5. Confirm these files exist:",
            f"   - `{out_dir / (PLATE_MODEL + '.fmu')}`",
            f"   - `{out_dir / (CONSTANT_MODEL + '.fmu')}`",
            "6. Run `python scripts/inspect_site_a_hx_modelica_interface.py`.",
            "7. Run `python scripts/smoke_test_site_a_hx_fmus.py`.",
            "",
            "## Interface Requirement",
            "",
            "The exported `modelDescription.xml` must expose `table_path`, nominal flows, heat-transfer parameters, and `eps`/nominal parameters as tunable parameters.",
            "",
        ]
    )
    with guide_path.open("w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    return guide_path


def dymola_command(dymola_exe: Path, mos_path: Path) -> list[str]:
    return [str(dymola_exe), "/nowindow", str(mos_path)]


def dymola_interface_egg(dymola_exe: Path) -> Path:
    return Path(dymola_exe).resolve().parents[1] / "Modelica" / "Library" / "python_interface" / "dymola.egg"


def _dymola_interface_factory(dymola_exe: Path):
    egg = dymola_interface_egg(dymola_exe)
    if not egg.is_file():
        raise FileNotFoundError(f"Dymola Python interface does not exist: {egg}")
    if str(egg) not in sys.path:
        sys.path.insert(0, str(egg))
    from dymola.dymola_interface import DymolaInterface

    return DymolaInterface


def export_with_dymola_interface(
    *,
    out_dir: Path = OUT_DIR,
    buildings_package: Path = BUILDINGS_PACKAGE,
    wrappers: Sequence[tuple[Path, str]] = ((PLATE_SOURCE, PLATE_MODEL), (CONSTANT_SOURCE, CONSTANT_MODEL)),
    dymola_exe: Path | None = None,
    interface_factory: Callable[..., object] | None = None,
) -> InterfaceExportResult:
    exe = dymola_exe or default_dymola_exe()
    factory = interface_factory or _dymola_interface_factory(exe)
    out_dir.mkdir(parents=True, exist_ok=True)
    dymola = None
    lines = []
    try:
        dymola = factory(dymolapath=str(exe), showwindow=False)
        dymola.ExecuteCommand(f'cd("{as_modelica_path(out_dir)}")')
        if not dymola.openModel(as_modelica_path(buildings_package), changeDirectory=False):
            return InterfaceExportResult(1, "\n".join(lines), f"Buildings package failed to load: {dymola.getLastError()}")
        lines.append(f"loaded Buildings package: {buildings_package}")
        dymola.ExecuteCommand("Advanced.FMI.AllowStringParameters=true")
        for source, model in wrappers:
            if not dymola.openModel(as_modelica_path(source), changeDirectory=False):
                return InterfaceExportResult(1, "\n".join(lines), f"{model} failed to load: {dymola.getLastError()}")
            lines.append(f"loaded wrapper: {model}")
            translated = dymola.translateModelFMU(model, False, model, fmiVersion="2", fmiType="cs")
            if not translated:
                return InterfaceExportResult(1, "\n".join(lines), f"{model} FMU export failed: {dymola.getLastError()}")
            lines.append(f"exported FMU: {translated}")
        return InterfaceExportResult(0, "\n".join(lines), "")
    except Exception as exc:  # noqa: BLE001 - report Dymola integration failures in the export log.
        return InterfaceExportResult(1, "\n".join(lines), f"{type(exc).__name__}: {exc}")
    finally:
        if dymola is not None:
            dymola.close()


def run_dymola_batch_export(
    mos_path: Path,
    dymola_exe: Path | None = None,
    timeout_sec: int = 600,
) -> subprocess.CompletedProcess[str]:
    exe = dymola_exe or default_dymola_exe()
    return subprocess.run(
        dymola_command(exe, mos_path),
        cwd=str(mos_path.parent),
        text=True,
        capture_output=True,
        check=False,
        timeout=timeout_sec,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="store_true", help="Invoke Dymola after writing the export .mos file.")
    parser.add_argument("--batch", action="store_true", help="Use the legacy /nowindow .mos batch invocation instead of the Python interface.")
    parser.add_argument("--dymola-exe", type=Path, default=None, help="Path to Dymola.exe.")
    parser.add_argument("--timeout-sec", type=int, default=600, help="Legacy --batch command-line timeout in seconds.")
    args = parser.parse_args(argv)

    mos_path = write_export_mos()
    guide_path = write_export_guide(mos_path)
    print(f"Wrote {mos_path}")
    print(f"Wrote {guide_path}")

    if not args.run:
        print("Not running Dymola. Review the .mos file or rerun with --run.")
        return 0

    log_path = OUT_DIR / "export_site_a_hx_fmus.log"
    try:
        proc = (
            run_dymola_batch_export(mos_path, args.dymola_exe, timeout_sec=args.timeout_sec)
            if args.batch
            else export_with_dymola_interface(dymola_exe=args.dymola_exe)
        )
    except subprocess.TimeoutExpired as exc:
        with log_path.open("w", encoding="utf-8", newline="\n") as f:
            f.write(f"returncode=timeout\nTimeout after {args.timeout_sec} seconds\n")
            f.write("STDOUT:\n")
            f.write((exc.stdout or "") if isinstance(exc.stdout, str) else str(exc.stdout or ""))
            f.write("\nSTDERR:\n")
            f.write((exc.stderr or "") if isinstance(exc.stderr, str) else str(exc.stderr or ""))
        print(f"Dymola export timed out after {args.timeout_sec} seconds.")
        print(f"Wrote {log_path}")
        return 124
    with log_path.open("w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(["returncode=" + str(proc.returncode), "STDOUT:", proc.stdout, "STDERR:", proc.stderr]))
    print(f"Wrote {log_path}")
    required_fmus = [OUT_DIR / f"{PLATE_MODEL}.fmu", OUT_DIR / f"{CONSTANT_MODEL}.fmu"]
    if proc.returncode != 0 or not all(path.is_file() for path in required_fmus):
        print(proc.stdout)
        print(proc.stderr)
        return proc.returncode or 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
