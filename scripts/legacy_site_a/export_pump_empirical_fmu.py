"""Export the minimal pump empirical Modelica model as an FMU."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Mapping


ROOT = Path(__file__).resolve().parents[1]
MODEL_PATH = ROOT / "models" / "pump" / "PumpEmpiricalPower.mo"
OUT_DIR = ROOT / "outputs" / "pump" / "stage4_modelica_interface" / "fmu"


def default_omc_exe(env: Mapping[str, str] | None = None) -> Path:
    env = env or os.environ
    home = env.get("OPENMODELICAHOME") or env.get("OPENMODELICA_HOME")
    if home:
        return Path(home) / "bin" / "omc.exe"
    found = shutil.which("omc")
    return Path(found) if found else Path("omc")


def as_modelica_path(path: Path) -> str:
    return str(path.resolve()).replace("\\", "/")


def build_export_mos(model_path: Path = MODEL_PATH, out_dir: Path = OUT_DIR) -> str:
    return "\n".join(
        [
            f'cd("{as_modelica_path(out_dir)}");',
            f'loadFile("{as_modelica_path(model_path)}");',
            'buildModelFMU(PumpEmpiricalPower, version="2.0", fmuType="cs");',
            "getErrorString();",
            "",
        ]
    )


def export_fmu(
    model_path: Path = MODEL_PATH,
    out_dir: Path = OUT_DIR,
    omc_exe: Path | None = None,
) -> tuple[Path, Path, subprocess.CompletedProcess[str]]:
    out_dir.mkdir(parents=True, exist_ok=True)
    mos_path = out_dir / "export_pump_empirical_fmu.mos"
    with mos_path.open("w", encoding="utf-8", newline="\n") as f:
        f.write(build_export_mos(model_path, out_dir))
    omc = omc_exe or default_omc_exe()
    proc = subprocess.run(
        [str(omc), str(mos_path)],
        cwd=str(out_dir),
        text=True,
        capture_output=True,
        check=False,
    )
    fmu_path = out_dir / "PumpEmpiricalPower.fmu"
    return fmu_path, mos_path, proc


def main() -> int:
    fmu_path, mos_path, proc = export_fmu()
    log_path = OUT_DIR / "export_pump_empirical_fmu.log"
    with log_path.open("w", encoding="utf-8", newline="\n") as f:
        f.write(
            "\n".join(
                [
                    f"returncode={proc.returncode}",
                    "STDOUT:",
                    proc.stdout,
                    "STDERR:",
                    proc.stderr,
                ]
            )
        )
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
