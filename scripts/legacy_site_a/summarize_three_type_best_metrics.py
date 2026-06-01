"""Summarize EIR, EEIR, and Carnot_TEva best-result metrics.

This script consumes existing best-result workbooks and best time-series CSVs.
It does not rerun FMUs and does not modify the reference ``Cali_EIR_BSU_CH1``
directory.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from summarize_two_type_best_metrics import (
    DEFAULT_EEIR_RESULTS,
    DEFAULT_EIR_RESULTS,
    ROOT,
    load_best_results,
    summary_rows_for_best,
    write_outputs,
)


DEFAULT_CARNOT_RESULTS = (
    ROOT
    / "outputs"
    / "electric_carnot_teva"
    / "simulation"
    / "carnot_multi_chiller_results_current_fmu.xlsx"
)
DEFAULT_OUTPUT = ROOT / "outputs" / "comparison" / "three_type" / "best_metrics_three_type_current.xlsx"
DEFAULT_TIMESERIES_DIR = ROOT / "outputs" / "comparison" / "three_type" / "timeseries"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build three-type best metric summary and comparison data.")
    parser.add_argument("--eir-results", type=Path, default=DEFAULT_EIR_RESULTS)
    parser.add_argument("--eeir-results", type=Path, default=DEFAULT_EEIR_RESULTS)
    parser.add_argument("--carnot-results", type=Path, default=DEFAULT_CARNOT_RESULTS)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--timeseries-dir", type=Path, default=DEFAULT_TIMESERIES_DIR)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    best = pd.concat(
        [
            load_best_results(args.eir_results, "EIR"),
            load_best_results(args.eeir_results, "EEIR"),
            load_best_results(args.carnot_results, "Carnot_TEva"),
        ],
        ignore_index=True,
        sort=False,
    )

    summary, manifest = summary_rows_for_best(best, args.timeseries_dir)
    write_outputs(summary, manifest, args.output)

    print(f"Summary workbook: {args.output}")
    print(f"Comparison time-series dir: {args.timeseries_dir}")
    print(f"Summary rows: {len(summary)}")
    print(f"Comparison files: {len(manifest)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
