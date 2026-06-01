"""Smoke-test the Dymola-exported MBL SpeedControlled_y pump FMU."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
from fmpy import simulate_fmu


ROOT = Path(__file__).resolve().parents[1]
FMU = ROOT / "outputs" / "pump" / "mbl_speed_system" / "fmu" / "SiteAPumpMblSpeedSystemCurve.fmu"
PARAMS = ROOT / "outputs" / "pump" / "mbl_speed_system" / "full_period_validation_metrics.csv"
TABLE_DIR = ROOT / "outputs" / "pump" / "site_a_tables"
OUT_DIR = ROOT / "outputs" / "pump" / "mbl_speed_system" / "fmu_smoke"


def build_fmu_input(table: pd.DataFrame) -> np.ndarray:
    return np.array(
        list(zip(pd.to_numeric(table["time_s"], errors="coerce").astype(float), pd.to_numeric(table["y_used"], errors="coerce").astype(float))),
        dtype=[("time", np.float64), ("y_in", np.float64)],
    )


def start_values(row: pd.Series) -> dict[str, float]:
    return {
        "m_flow_nominal": float(row["m_flow_nominal"]),
        "dp_nominal": 300000.0,
        "dp_system_nominal": 250000.0,
        "P_scale": 1.0,
        "y_min": 0.05,
        "y_max": 1.2,
    }


def run_smoke(pump: str = "CDWP_03", rows: int = 12) -> tuple[pd.DataFrame, dict[str, object]]:
    params = pd.read_csv(PARAMS)
    row = params[params["pump"] == pump].iloc[0]
    table = pd.read_csv(TABLE_DIR / f"{pump}_window_table.csv").head(rows).copy()
    result = simulate_fmu(
        str(FMU),
        start_values=start_values(row),
        input=build_fmu_input(table),
        output=["P_s", "m_flow_s", "dp_s", "head_s", "y_s"],
        stop_time=float(table["time_s"].iloc[-1]),
        output_interval=300.0,
    )
    out = pd.DataFrame(result)
    summary = {
        "pump": pump,
        "rows": int(len(out)),
        "finite_outputs": bool(np.isfinite(out[["P_s", "m_flow_s", "dp_s", "head_s", "y_s"]]).all().all()),
        "first_P_s": float(out["P_s"].iloc[0]),
        "first_m_flow_s": float(out["m_flow_s"].iloc[0]),
        "first_head_s": float(out["head_s"].iloc[0]),
    }
    return out, summary


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out, summary = run_smoke()
    csv_path = OUT_DIR / "CDWP_03_mbl_speed_system_fmu_smoke_timeseries.csv"
    md_path = OUT_DIR / "mbl_speed_system_fmu_smoke_report.md"
    out.to_csv(csv_path, index=False)
    with md_path.open("w", encoding="utf-8", newline="\n") as f:
        f.write("# Pump MBL Speed/System FMU Smoke Test\n\n")
        for key, value in summary.items():
            f.write(f"- {key}: {value}\n")
    print(f"Wrote {csv_path}")
    print(f"Wrote {md_path}")
    print(summary)
    return 0 if summary["finite_outputs"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
