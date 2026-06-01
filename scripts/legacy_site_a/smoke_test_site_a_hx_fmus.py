"""Smoke test exported Site A heat exchanger FMUs on a one-hour HX_02 window."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

try:
    from calibrate_site_a_hx_fmus import (
        CONST_FMU,
        PLATE_FMU,
        TABLE_DIR,
        build_candidate_grid,
        flatten_metrics,
        simulate_case,
        start_values,
    )
    from prepare_site_a_hx_fmu_tables import write_dymola_table
except ImportError:
    from scripts.calibrate_site_a_hx_fmus import (
        CONST_FMU,
        PLATE_FMU,
        TABLE_DIR,
        build_candidate_grid,
        flatten_metrics,
        simulate_case,
        start_values,
    )
    from scripts.prepare_site_a_hx_fmu_tables import write_dymola_table


ROOT = Path(__file__).resolve().parents[1]
HX_OUT = ROOT / "outputs" / "heat_exchanger"
NOMINALS = HX_OUT / "nominals" / "site_a_hx_nominals.csv"
OUT_DIR = HX_OUT / "modelica_interface" / "fmu_smoke"
REQUIRED_FMUS = [PLATE_FMU, CONST_FMU]


def missing_required_fmus(paths: list[Path] | None = None) -> list[Path]:
    check = paths or REQUIRED_FMUS
    return [path for path in check if not path.exists()]


def write_missing_fmu_report(missing: list[Path], out_dir: Path = OUT_DIR) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    report = out_dir / "fmu_smoke_report.md"
    with report.open("w", encoding="utf-8", newline="\n") as f:
        f.write("# Site A HX FMU Smoke Test\n\n")
        f.write("Status: `blocked_missing_fmu`\n\n")
        f.write("Missing FMUs:\n")
        for path in missing:
            f.write(f"- `{path}`\n")
    return report


def smoke_table(hx: str = "HX_02", rows: int = 13) -> tuple[pd.DataFrame, Path]:
    table_path = TABLE_DIR / f"{hx}_fmu_table.csv"
    source = pd.read_csv(table_path)
    work = source.iloc[:rows].copy()
    work["time_s"] = [float(i * 300) for i in range(len(work))]
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    txt_path = OUT_DIR / f"{hx}_one_hour_smoke_table.txt"
    csv_path = OUT_DIR / f"{hx}_one_hour_smoke_table.csv"
    work.to_csv(csv_path, index=False, encoding="utf-8-sig")
    write_dymola_table(txt_path, work)
    return work, txt_path


def candidate_for_model(nominals: dict[str, object], model: str) -> dict[str, object]:
    for candidate in build_candidate_grid(nominals):
        if candidate["model"] == model:
            return candidate
    raise ValueError(f"No candidate for {model}")


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    missing = missing_required_fmus()
    if missing:
        report = write_missing_fmu_report(missing)
        print(f"Missing required FMUs: {', '.join(str(path) for path in missing)}")
        print(f"Wrote {report}")
        return 2
    if not NOMINALS.exists():
        print(f"Missing nominal file: {NOMINALS}")
        return 1

    nom = pd.read_csv(NOMINALS)
    row = nom.loc[nom["hx"] == "HX_02"]
    if row.empty:
        print("HX_02 nominal row not found. Run prepare_site_a_hx_fmu_tables.py first.")
        return 1
    table, txt_path = smoke_table()
    rows = []
    for model, fmu in [("PlateEffectivenessNTU", PLATE_FMU), ("ConstantEffectiveness", CONST_FMU)]:
        candidate = candidate_for_model(row.iloc[0].to_dict(), model)
        values = start_values(txt_path, candidate)
        result = simulate_case(fmu, values, float(table["time_s"].iloc[-1]), OUT_DIR / f"{model}_smoke_log.md")
        ts_path = OUT_DIR / f"HX_02_{model}_smoke_timeseries.csv"
        result.to_csv(ts_path, index=False, encoding="utf-8-sig")
        metrics = flatten_metrics(result, "HX_02", model, "smoke")
        for metric in metrics:
            metric["timeseries"] = str(ts_path)
            rows.append(metric)

    metrics_df = pd.DataFrame(rows)
    metrics_path = OUT_DIR / "fmu_smoke_metrics.csv"
    metrics_df.to_csv(metrics_path, index=False, encoding="utf-8-sig")
    report = OUT_DIR / "fmu_smoke_report.md"
    with report.open("w", encoding="utf-8", newline="\n") as f:
        f.write("# Site A HX FMU Smoke Test\n\n")
        f.write("Status: `completed`\n\n")
        f.write(f"- Table: `{txt_path}`\n")
        f.write(f"- Metrics: `{metrics_path}`\n")
    print(f"Output: {OUT_DIR}")
    print(metrics_df[["hx", "model", "variable", "N", "RMSE", "CVRMSE"]].to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
