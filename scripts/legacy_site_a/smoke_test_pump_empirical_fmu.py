"""Smoke-test the exported pump empirical FMU with fitted Site A parameters."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
from fmpy import simulate_fmu


ROOT = Path(__file__).resolve().parents[1]
FMU = ROOT / "outputs" / "pump" / "stage4_modelica_interface" / "fmu" / "PumpEmpiricalPower.fmu"
PARAMS = ROOT / "outputs" / "pump" / "auto_model_site_a" / "best_pump_parameters.csv"
TABLE_DIR = ROOT / "outputs" / "pump" / "site_a_tables"
OUT_DIR = ROOT / "outputs" / "pump" / "stage4_modelica_interface" / "fmu_smoke"


def build_fmu_input(table: pd.DataFrame) -> np.ndarray:
    return np.array(
        list(
            zip(
                pd.to_numeric(table["time_s"], errors="coerce").astype(float),
                pd.to_numeric(table["m_flow_kg_s"], errors="coerce").astype(float),
                pd.to_numeric(table["y_used"], errors="coerce").astype(float),
            )
        ),
        dtype=[("time", np.float64), ("m_flow_in", np.float64), ("y_in", np.float64)],
    )


def start_values(row: pd.Series) -> dict[str, float]:
    keys = ["P_nominal", "m_flow_nominal", "y_min", "y_max", "c0", "c1", "c2", "c3", "c4"]
    return {key: float(row[key]) for key in keys}


def run_smoke(pump: str = "CDWP_03", rows: int = 12) -> tuple[pd.DataFrame, dict[str, object]]:
    params = pd.read_csv(PARAMS)
    row = params[params["pump"] == pump].iloc[0]
    table = pd.read_csv(TABLE_DIR / f"{pump}_window_table.csv").head(rows).copy()
    input_data = build_fmu_input(table)
    result = simulate_fmu(
        str(FMU),
        start_values=start_values(row),
        input=input_data,
        output=["P_s", "m_flow_s", "y_s"],
        stop_time=float(table["time_s"].iloc[-1]),
        output_interval=300.0,
    )
    out = pd.DataFrame(result)
    out["P_meas_W"] = table["P_meas_W"].to_numpy(dtype=float)[: len(out)]
    out["P_residual_W"] = out["P_s"] - out["P_meas_W"]
    summary = {
        "pump": pump,
        "rows": int(len(out)),
        "finite_P_s": bool(np.isfinite(out["P_s"]).all()),
        "first_P_s": float(out["P_s"].iloc[0]),
        "last_P_s": float(out["P_s"].iloc[-1]),
        "mean_abs_residual_W": float(out["P_residual_W"].abs().mean()),
    }
    return out, summary


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    result, summary = run_smoke()
    csv_path = OUT_DIR / "CDWP_03_fmu_smoke_timeseries.csv"
    md_path = OUT_DIR / "fmu_smoke_report.md"
    result.to_csv(csv_path, index=False)
    with md_path.open("w", encoding="utf-8", newline="\n") as f:
        f.write("# Pump Empirical FMU Smoke Test\n\n")
        for key, value in summary.items():
            f.write(f"- {key}: {value}\n")
    print(f"Wrote {csv_path}")
    print(f"Wrote {md_path}")
    print(summary)
    return 0 if summary["finite_P_s"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
