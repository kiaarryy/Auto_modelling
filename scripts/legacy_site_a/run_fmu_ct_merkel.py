"""Run and check the cooling tower Merkel FMU with FMPy."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Dict, Iterable, Mapping, Optional, Sequence

import numpy as np
import pandas as pd
from fmpy import read_model_description, simulate_fmu


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_FMU = ROOT / "outputs" / "cooling_tower" / "fmus" / "CTM_0FMU.fmu"
DEFAULT_TABLE = (
    ROOT
    / "CT_Model"
    / "results"
    / "ct01_yorkcalc_params_v1"
    / "ct01_dataset_modelling_dymola_cells2_v3_withPFan.txt"
)
DEFAULT_OUTPUT_DIR = ROOT / "outputs" / "cooling_tower" / "merkel"
OUTPUTS = ["TOut_m", "TOut_s", "Q_m", "Q_s", "P_m", "P_s"]
TABLE_PATH_PARAMETERS = ["tableFileName", "Tout1.fileName"]
PAIR_MAP = {
    "TOut": ("TOut_s", "TOut_m"),
    "Q": ("Q_s", "Q_m"),
    "P": ("P_s", "P_m"),
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fmu", type=Path, default=DEFAULT_FMU)
    parser.add_argument("--table-file", type=Path, default=DEFAULT_TABLE)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--start-time", type=float, default=0.0)
    parser.add_argument("--stop-time", type=float, default=3600.0)
    parser.add_argument("--output-interval", type=float, default=300.0)
    parser.add_argument("--start-values-json", type=Path)
    parser.add_argument("--timeseries-name", default="ct_merkel_timeseries.csv")
    parser.add_argument("--metrics-name", default="ct_merkel_metrics.csv")
    return parser.parse_args()


def load_start_values(path: Optional[Path]) -> Dict[str, object]:
    if path is None:
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Start values JSON must be an object: {path}")
    return dict(data)


def require_paths(paths: Iterable[Path]) -> None:
    missing = [str(path) for path in paths if not path.exists()]
    if missing:
        raise FileNotFoundError("Missing required path(s): " + "; ".join(missing))


def metric_row(label: str, simulated: Sequence[float], measured: Sequence[float]) -> Dict[str, float | int | str]:
    sim = pd.to_numeric(pd.Series(simulated), errors="coerce").to_numpy(dtype=float)
    mea = pd.to_numeric(pd.Series(measured), errors="coerce").to_numpy(dtype=float)
    mask = np.isfinite(sim) & np.isfinite(mea)
    sim = sim[mask]
    mea = mea[mask]
    n = len(sim)
    if n == 0:
        return {
            "variable": label,
            "N": 0,
            "RMSE": math.nan,
            "MAE": math.nan,
            "MBE": math.nan,
            "NMBE_%": math.nan,
            "CVRMSE_%": math.nan,
            "MAPE_%": math.nan,
            "R2": math.nan,
        }
    err = sim - mea
    rmse = float(np.sqrt(np.mean(err**2)))
    mae = float(np.mean(np.abs(err)))
    mbe = float(np.mean(err))
    mean_mea = float(np.mean(mea))
    nz = np.abs(mea) > 1e-9
    ss_res = float(np.sum(err**2))
    ss_tot = float(np.sum((mea - mean_mea) ** 2))
    return {
        "variable": label,
        "N": n,
        "RMSE": rmse,
        "MAE": mae,
        "MBE": mbe,
        "NMBE_%": float(mbe / mean_mea * 100.0) if mean_mea != 0 else math.nan,
        "CVRMSE_%": float(rmse / mean_mea * 100.0) if mean_mea != 0 else math.nan,
        "MAPE_%": float(np.mean(np.abs(err[nz] / mea[nz])) * 100.0) if np.any(nz) else math.nan,
        "R2": float(1.0 - ss_res / ss_tot) if ss_tot != 0 else math.nan,
    }


def build_metrics(df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for label, (sim_col, mea_col) in PAIR_MAP.items():
        rows.append(metric_row(label, df[sim_col], df[mea_col]))
    return pd.DataFrame(rows)


def get_variable_names(fmu: Path) -> Dict[str, object]:
    md = read_model_description(str(fmu), validate=False)
    return {v.name: v for v in md.modelVariables}


def validate_fmu_interface(fmu: Path) -> None:
    variables = get_variable_names(fmu)
    missing = [name for name in OUTPUTS if name not in variables]
    if missing:
        raise ValueError(f"FMU missing required output variable(s): {missing}")
    for name in OUTPUTS:
        if variables[name].causality != "output":
            raise ValueError(f"{name} exists but is not an output: {variables[name].causality}")
    table_params = [name for name in TABLE_PATH_PARAMETERS if name in variables]
    if not table_params:
        raise ValueError(
            "FMU missing table path parameter. Expected one of: "
            + ", ".join(TABLE_PATH_PARAMETERS)
        )


def run_case(
    fmu: Path,
    table_file: Path,
    start_values: Mapping[str, object],
    start_time: float,
    stop_time: float,
    output_interval: float,
) -> pd.DataFrame:
    values = dict(start_values)
    variables = get_variable_names(fmu)
    table_path = str(table_file).replace("\\", "/")
    for name in TABLE_PATH_PARAMETERS:
        if name in variables:
            values[name] = table_path
    result = simulate_fmu(
        str(fmu),
        start_time=start_time,
        stop_time=stop_time,
        output_interval=output_interval,
        output=OUTPUTS,
        start_values=values,
        fmi_type="CoSimulation",
    )
    return pd.DataFrame.from_records(result)


def main() -> int:
    args = parse_args()
    require_paths([args.fmu, args.table_file])
    validate_fmu_interface(args.fmu)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    start_values = load_start_values(args.start_values_json)
    timeseries = run_case(
        args.fmu,
        args.table_file,
        start_values,
        args.start_time,
        args.stop_time,
        args.output_interval,
    )
    metrics = build_metrics(timeseries)
    timeseries.to_csv(args.output_dir / args.timeseries_name, index=False)
    metrics.to_csv(args.output_dir / args.metrics_name, index=False)
    print(f"Timeseries: {args.output_dir / args.timeseries_name}")
    print(f"Metrics: {args.output_dir / args.metrics_name}")
    print(metrics.to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
