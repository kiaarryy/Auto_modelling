"""Export the Site A MBL SpeedControlled_y pump wrapper as an FMU."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Mapping
import os


ROOT = Path(__file__).resolve().parents[1]
BUILDINGS_PACKAGE = Path(r"E:\APP\dymola2025\Modelica\Buildings 12.1.0\package.mo")
MODEL_PATH = ROOT / "models" / "pump" / "SiteAPumpMblSpeedSystemCurve.mo"
OUT_DIR = ROOT / "outputs" / "pump" / "mbl_speed_system" / "fmu"
MODEL_NAME = "SiteAPumpMblSpeedSystemCurve"


def as_modelica_path(path: Path) -> str:
    return str(path.resolve()).replace("\\", "/")


def default_omc_exe(env: Mapping[str, str] | None = None) -> Path:
    env = env or os.environ
    home = env.get("OPENMODELICAHOME") or env.get("OPENMODELICA_HOME")
    if home:
        return Path(home) / "bin" / "omc.exe"
    found = shutil.which("omc")
    return Path(found) if found else Path("omc")


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
    model_path: Path = MODEL_PATH,
    buildings_package: Path = BUILDINGS_PACKAGE,
    out_dir: Path = OUT_DIR,
) -> str:
    return "\n".join(
        [
            f'cd("{as_modelica_path(out_dir)}");',
            f'loadFile("{as_modelica_path(buildings_package)}");',
            "getErrorString();",
            f'loadFile("{as_modelica_path(model_path)}");',
            "getErrorString();",
            f'buildModelFMU({MODEL_NAME}, version="2.0", fmuType="cs");',
            "getErrorString();",
            "",
        ]
    )


def build_dymola_export_mos(
    model_path: Path = MODEL_PATH,
    buildings_package: Path = BUILDINGS_PACKAGE,
    out_dir: Path = OUT_DIR,
) -> str:
    return "\n".join(
        [
            f'cd("{as_modelica_path(out_dir)}");',
            f'openModel("{as_modelica_path(buildings_package)}", changeDirectory=false);',
            f'openModel("{as_modelica_path(model_path)}", changeDirectory=false);',
            f'translateModelFMU("{MODEL_NAME}", false, "{MODEL_NAME}", fmiVersion="2", fmiType="cs");',
            "getLastError();",
            "exit();",
            "",
        ]
    )


def export_fmu(
    model_path: Path = MODEL_PATH,
    out_dir: Path = OUT_DIR,
    omc_exe: Path | None = None,
    timeout_sec: int = 600,
) -> tuple[Path, Path, subprocess.CompletedProcess[str]]:
    out_dir.mkdir(parents=True, exist_ok=True)
    mos_path = out_dir / "export_pump_mbl_speed_system_fmu.mos"
    with mos_path.open("w", encoding="utf-8", newline="\n") as f:
        f.write(build_export_mos(model_path=model_path, out_dir=out_dir))
    omc = omc_exe or default_omc_exe()
    proc = subprocess.run(
        [str(omc), str(mos_path)],
        cwd=str(out_dir),
        text=True,
        capture_output=True,
        check=False,
        timeout=timeout_sec,
    )
    return out_dir / f"{MODEL_NAME}.fmu", mos_path, proc


def export_fmu_with_dymola(
    model_path: Path = MODEL_PATH,
    out_dir: Path = OUT_DIR,
    dymola_exe: Path | None = None,
    timeout_sec: int = 600,
) -> tuple[Path, Path, subprocess.CompletedProcess[str]]:
    out_dir.mkdir(parents=True, exist_ok=True)
    mos_path = out_dir / "export_pump_mbl_speed_system_dymola.mos"
    with mos_path.open("w", encoding="utf-8", newline="\n") as f:
        f.write(build_dymola_export_mos(model_path=model_path, out_dir=out_dir))
    exe = dymola_exe or default_dymola_exe()
    proc = subprocess.run(
        [str(exe), "/nowindow", str(mos_path)],
        cwd=str(out_dir),
        text=True,
        capture_output=True,
        check=False,
        timeout=timeout_sec,
    )
    return out_dir / f"{MODEL_NAME}.fmu", mos_path, proc


def main() -> int:
    fmu_path, mos_path, proc = export_fmu_with_dymola()
    log_path = OUT_DIR / "export_pump_mbl_speed_system_dymola.log"
    with log_path.open("w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(["returncode=" + str(proc.returncode), "STDOUT:", proc.stdout, "STDERR:", proc.stderr]))
    print(f"Wrote {mos_path}")
    print(f"Wrote {log_path}")
    if proc.returncode != 0 or not fmu_path.exists():
        print(proc.stdout)
        print(proc.stderr)
        return 1
    print(f"Wrote {fmu_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
