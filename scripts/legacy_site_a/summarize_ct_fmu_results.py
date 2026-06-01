"""Summarize cooling tower FMU metric CSV files."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import List

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "outputs" / "cooling_tower" / "comparison" / "ct_fmu_metrics_summary.csv"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--metrics",
        type=Path,
        nargs="*",
        default=[
            ROOT / "outputs" / "cooling_tower" / "merkel" / "ct_merkel_metrics.csv",
            ROOT / "outputs" / "cooling_tower" / "yorkcalc" / "ct_yorkcalc_metrics.csv",
        ],
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def model_name_from_path(path: Path) -> str:
    text = path.as_posix().lower()
    if "yorkcalc" in text:
        return "YorkCalc"
    if "merkel" in text:
        return "Merkel"
    return path.stem


def main() -> int:
    args = parse_args()
    frames: List[pd.DataFrame] = []
    for path in args.metrics:
        if not path.exists():
            print(f"Skipping missing metrics file: {path}")
            continue
        df = pd.read_csv(path)
        df.insert(0, "model", model_name_from_path(path))
        df.insert(1, "source", str(path))
        frames.append(df)
    if not frames:
        raise FileNotFoundError("No metrics files were found.")
    out = pd.concat(frames, ignore_index=True, sort=False)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(args.output, index=False)
    print(f"Summary: {args.output}")
    print(out.to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
