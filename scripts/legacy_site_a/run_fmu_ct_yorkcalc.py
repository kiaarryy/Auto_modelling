"""Run and check the cooling tower YorkCalc FMU with FMPy."""

from __future__ import annotations

from pathlib import Path

import run_fmu_ct_merkel as runner


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = runner.parse_args()
    parser.fmu = (
        ROOT / "outputs" / "cooling_tower" / "fmus" / "Cooling_Tower_YorkCalc.fmu"
        if parser.fmu == runner.DEFAULT_FMU
        else parser.fmu
    )
    parser.output_dir = (
        ROOT / "outputs" / "cooling_tower" / "yorkcalc"
        if parser.output_dir == runner.DEFAULT_OUTPUT_DIR
        else parser.output_dir
    )
    parser.timeseries_name = (
        "ct_yorkcalc_timeseries.csv"
        if parser.timeseries_name == "ct_merkel_timeseries.csv"
        else parser.timeseries_name
    )
    parser.metrics_name = (
        "ct_yorkcalc_metrics.csv"
        if parser.metrics_name == "ct_merkel_metrics.csv"
        else parser.metrics_name
    )
    runner.require_paths([parser.fmu, parser.table_file])
    runner.validate_fmu_interface(parser.fmu)
    parser.output_dir.mkdir(parents=True, exist_ok=True)
    start_values = runner.load_start_values(parser.start_values_json)
    timeseries = runner.run_case(
        parser.fmu,
        parser.table_file,
        start_values,
        parser.start_time,
        parser.stop_time,
        parser.output_interval,
    )
    metrics = runner.build_metrics(timeseries)
    timeseries.to_csv(parser.output_dir / parser.timeseries_name, index=False)
    metrics.to_csv(parser.output_dir / parser.metrics_name, index=False)
    print(f"Timeseries: {parser.output_dir / parser.timeseries_name}")
    print(f"Metrics: {parser.output_dir / parser.metrics_name}")
    print(metrics.to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
