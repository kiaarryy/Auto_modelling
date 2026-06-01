"""Summarize pump model-candidate selection status.

This report separates two decisions that should not be conflated:

1. empirical power model-family selection, which is currently implemented; and
2. Modelica Buildings Library pump-type selection, which is still planned.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
AUTO_MODEL_DIR = ROOT / "outputs" / "pump" / "auto_model_site_a"
MBL_SPEED_DIR = ROOT / "outputs" / "pump" / "mbl_speed_system"
OUT_DIR = ROOT / "outputs" / "pump" / "model_selection"


def build_candidate_inventory() -> list[dict[str, object]]:
    return [
        {
            "candidate_id": "empirical_power_flow_speed",
            "candidate_group": "implemented_empirical",
            "modelica_class": "models/pump/PumpEmpiricalPower.mo",
            "input_contract": "measured m_flow_kg_s + normalized speed y",
            "predicts": "P_s; passes through m_flow_s",
            "validation_target": "P_meas_W",
            "implementation_status": "implemented",
            "selection_status": "selected_per_pump_by_full_period_CVRMSE",
            "blocking_reason": "",
        },
        {
            "candidate_id": "mbl_speedcontrolled_y_system_curve",
            "candidate_group": "implemented_mbl",
            "modelica_class": "Buildings.Fluid.Movers.SpeedControlled_y + Data.Generic + system resistance",
            "input_contract": "normalized speed y; system curve/flow solved by hydraulic network",
            "predicts": "P_s, m_flow_s, dp_s/head_s",
            "validation_target": "P_meas_W and m_flow_m; head_s is inferred unless head data is added",
            "implementation_status": "implemented_fmu_smoke_tested",
            "selection_status": "selected_per_pump_by_power_plus_flow_CVRMSE",
            "blocking_reason": "head cannot be validated without measured pump head/DP",
        },
        {
            "candidate_id": "mbl_flowcontrolled_m_flow",
            "candidate_group": "planned_mbl_baseline",
            "modelica_class": "Buildings.Fluid.Movers.FlowControlled_m_flow + Data.Generic",
            "input_contract": "measured m_flow_kg_s as prescribed flow",
            "predicts": "P_s; dp/head only model-inferred",
            "validation_target": "P_meas_W only; flow cannot be scored because it is an input",
            "implementation_status": "planned",
            "selection_status": "not_yet_run",
            "blocking_reason": "wrapper and runner not implemented",
        },
        {
            "candidate_id": "mbl_flowcontrolled_dp",
            "candidate_group": "blocked_mbl",
            "modelica_class": "Buildings.Fluid.Movers.FlowControlled_dp + Data.Generic",
            "input_contract": "pump head/DP setpoint or measured pump DP",
            "predicts": "P_s and possibly m_flow_s",
            "validation_target": "P_meas_W and m_flow_m if hydraulic boundary is meaningful",
            "implementation_status": "blocked",
            "selection_status": "not_eligible",
            "blocking_reason": "missing measured pump head/DP",
        },
        {
            "candidate_id": "mbl_preconfigured_speedcontrolled_y",
            "candidate_group": "planned_mbl_baseline",
            "modelica_class": "Buildings.Fluid.Movers.Preconfigured.SpeedControlled_y",
            "input_contract": "normalized speed y + nominal m_flow/dp",
            "predicts": "P_s, m_flow_s, dp_s/head_s",
            "validation_target": "P_meas_W and m_flow_m; head_s inferred",
            "implementation_status": "planned",
            "selection_status": "not_yet_run",
            "blocking_reason": "requires assumed or calibrated dp_nominal/system curve",
        },
    ]


def summarize_empirical_best(best_metrics: pd.DataFrame) -> dict[str, Any]:
    if best_metrics.empty:
        return {
            "pumps_calibrated": 0,
            "accepted_pumps": 0,
            "median_full_cvrmse_pct": np.nan,
            "max_full_cvrmse_pct": np.nan,
            "median_full_nmbe_pct": np.nan,
            "family_counts": {},
        }
    accepted = best_metrics["accepted_full_period"].astype(str).str.lower() == "true"
    return {
        "pumps_calibrated": int(len(best_metrics)),
        "accepted_pumps": int(accepted.sum()),
        "median_full_cvrmse_pct": float(best_metrics["full_cvrmse_pct"].median()),
        "max_full_cvrmse_pct": float(best_metrics["full_cvrmse_pct"].max()),
        "median_full_nmbe_pct": float(best_metrics["full_nmbe_pct"].median()),
        "family_counts": dict(Counter(best_metrics["family"])),
    }


def summarize_mbl_speed_best(best_metrics: pd.DataFrame) -> dict[str, Any]:
    if best_metrics.empty:
        return {
            "pumps_calibrated": 0,
            "accepted_pumps": 0,
            "median_full_P_cvrmse_pct": np.nan,
            "median_full_flow_cvrmse_pct": np.nan,
            "max_full_P_cvrmse_pct": np.nan,
            "max_full_flow_cvrmse_pct": np.nan,
            "variant_counts": {},
        }
    accepted = best_metrics["accepted_full_period"].astype(str).str.lower() == "true"
    return {
        "pumps_calibrated": int(len(best_metrics)),
        "accepted_pumps": int(accepted.sum()),
        "median_full_P_cvrmse_pct": float(best_metrics["full_P_cvrmse_pct"].median()),
        "median_full_flow_cvrmse_pct": float(best_metrics["full_flow_cvrmse_pct"].median()),
        "max_full_P_cvrmse_pct": float(best_metrics["full_P_cvrmse_pct"].max()),
        "max_full_flow_cvrmse_pct": float(best_metrics["full_flow_cvrmse_pct"].max()),
        "variant_counts": dict(Counter(best_metrics["variant"])),
    }


def compare_power_only(empirical: pd.DataFrame, mbl_speed: pd.DataFrame) -> pd.DataFrame:
    if empirical.empty:
        return pd.DataFrame()
    emp = empirical[["pump", "family", "full_cvrmse_pct", "full_nmbe_pct"]].rename(
        columns={
            "family": "empirical_family",
            "full_cvrmse_pct": "empirical_P_cvrmse_pct",
            "full_nmbe_pct": "empirical_P_nmbe_pct",
        }
    )
    if mbl_speed.empty:
        emp["mbl_variant"] = ""
        emp["mbl_P_cvrmse_pct"] = np.nan
        emp["mbl_flow_cvrmse_pct"] = np.nan
        emp["power_only_winner"] = "empirical_power_flow_speed"
        return emp
    mbl = mbl_speed[["pump", "variant", "full_P_cvrmse_pct", "full_flow_cvrmse_pct"]].rename(
        columns={
            "variant": "mbl_variant",
            "full_P_cvrmse_pct": "mbl_P_cvrmse_pct",
            "full_flow_cvrmse_pct": "mbl_flow_cvrmse_pct",
        }
    )
    out = emp.merge(mbl, on="pump", how="left")
    out["power_only_winner"] = np.where(
        out["mbl_P_cvrmse_pct"].notna() & (out["mbl_P_cvrmse_pct"] < out["empirical_P_cvrmse_pct"]),
        "mbl_speedcontrolled_y_system_curve",
        "empirical_power_flow_speed",
    )
    return out


def evaluate_selection_status(
    candidate_inventory: list[dict[str, object]],
    best_metrics: pd.DataFrame,
    mbl_speed_metrics: pd.DataFrame | None = None,
) -> dict[str, object]:
    mbl_speed_metrics = mbl_speed_metrics if mbl_speed_metrics is not None else pd.DataFrame()
    empirical_complete = not best_metrics.empty and "full_cvrmse_pct" in best_metrics
    implemented_mbl = [row for row in candidate_inventory if str(row["candidate_group"]) == "implemented_mbl"]
    mbl_complete = bool(implemented_mbl) and not mbl_speed_metrics.empty
    if empirical_complete and not mbl_complete:
        overall = "partial_empirical_only"
    elif empirical_complete and mbl_complete:
        overall = "current_implemented_candidate_selection_complete"
    else:
        overall = "not_started_or_no_metrics"
    return {
        "overall_status": overall,
        "empirical_family_selection_complete": bool(empirical_complete),
        "mbl_type_selection_complete": bool(mbl_complete),
        "implemented_mbl_candidate_count": len(implemented_mbl),
        "next_required_step": (
            "add FlowControlled_m_flow MBL baseline and tighten FMU parameter coupling to calibration outputs"
            if mbl_complete
            else "implement and validate MBL SpeedControlled_y system-curve candidate"
        ),
    }


def markdown_table(df: pd.DataFrame) -> str:
    headers = list(df.columns)
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join(["---"] * len(headers)) + " |",
    ]
    for _, row in df.iterrows():
        values = []
        for col in headers:
            val = row[col]
            if isinstance(val, float):
                values.append("" if np.isnan(val) else f"{val:.4g}")
            else:
                values.append(str(val).replace("|", "/"))
        lines.append("| " + " | ".join(values) + " |")
    return "\n".join(lines)


def write_report(
    inventory: pd.DataFrame,
    best: pd.DataFrame,
    mbl_speed: pd.DataFrame,
    power_comparison: pd.DataFrame,
    empirical_summary: dict[str, Any],
    mbl_summary: dict[str, Any],
    status: dict[str, object],
    path: Path,
) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as f:
        f.write("# Site A Pump Model Selection Status\n\n")
        f.write(f"- Overall status: `{status['overall_status']}`\n")
        f.write(f"- Empirical family selection complete: `{status['empirical_family_selection_complete']}`\n")
        f.write(f"- MBL pump type selection complete: `{status['mbl_type_selection_complete']}`\n")
        f.write(f"- Next required step: {status['next_required_step']}\n\n")
        f.write("## Implemented Empirical Selection\n\n")
        f.write(f"- Pumps calibrated: {empirical_summary['pumps_calibrated']}\n")
        f.write(f"- Accepted pumps: {empirical_summary['accepted_pumps']}\n")
        f.write(f"- Median full-period CVRMSE: {empirical_summary['median_full_cvrmse_pct']:.4g}%\n")
        f.write(f"- Maximum full-period CVRMSE: {empirical_summary['max_full_cvrmse_pct']:.4g}%\n")
        f.write(f"- Selected family counts: {empirical_summary['family_counts']}\n\n")
        f.write("## Implemented MBL Speed/System Candidate\n\n")
        f.write(f"- Pumps calibrated: {mbl_summary['pumps_calibrated']}\n")
        f.write(f"- Accepted pumps: {mbl_summary['accepted_pumps']}\n")
        f.write(f"- Median full-period power CVRMSE: {mbl_summary['median_full_P_cvrmse_pct']:.4g}%\n")
        f.write(f"- Median full-period flow CVRMSE: {mbl_summary['median_full_flow_cvrmse_pct']:.4g}%\n")
        f.write(f"- Selected variant counts: {mbl_summary['variant_counts']}\n\n")
        f.write("Head is still inferred only because no measured pump head/DP exists.\n\n")
        f.write("## Candidate Inventory\n\n")
        f.write(markdown_table(inventory))
        f.write("\n\n")
        if not best.empty:
            cols = ["pump", "family", "full_cvrmse_pct", "full_nmbe_pct", "full_r2", "accepted_full_period"]
            f.write("## Current Best Implemented Models\n\n")
            f.write(markdown_table(best.sort_values("full_cvrmse_pct")[cols]))
            f.write("\n")
        if not mbl_speed.empty:
            cols = ["pump", "variant", "full_P_cvrmse_pct", "full_flow_cvrmse_pct", "accepted_full_period", "head_validation_status"]
            f.write("\n## MBL Speed/System Best Variants\n\n")
            f.write(markdown_table(mbl_speed.sort_values("full_P_cvrmse_pct")[cols]))
            f.write("\n")
        if not power_comparison.empty:
            cols = [
                "pump",
                "empirical_family",
                "empirical_P_cvrmse_pct",
                "mbl_variant",
                "mbl_P_cvrmse_pct",
                "mbl_flow_cvrmse_pct",
                "power_only_winner",
            ]
            f.write("\n## Power-Only Winner Comparison\n\n")
            f.write(markdown_table(power_comparison.sort_values("pump")[cols]))
            f.write("\n")


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    inventory = pd.DataFrame(build_candidate_inventory())
    best_path = AUTO_MODEL_DIR / "full_period_validation_metrics.csv"
    mbl_path = MBL_SPEED_DIR / "full_period_validation_metrics.csv"
    best = pd.read_csv(best_path) if best_path.exists() else pd.DataFrame()
    mbl_speed = pd.read_csv(mbl_path) if mbl_path.exists() else pd.DataFrame()
    empirical_summary = summarize_empirical_best(best)
    mbl_summary = summarize_mbl_speed_best(mbl_speed)
    power_comparison = compare_power_only(best, mbl_speed)
    status = evaluate_selection_status(inventory.to_dict("records"), best, mbl_speed)

    inventory_path = OUT_DIR / "site_a_pump_model_candidate_inventory.csv"
    status_path = OUT_DIR / "site_a_pump_model_selection_status.csv"
    comparison_path = OUT_DIR / "site_a_pump_power_only_winner_comparison.csv"
    report_path = OUT_DIR / "site_a_pump_model_selection_status.md"

    inventory.to_csv(inventory_path, index=False)
    power_comparison.to_csv(comparison_path, index=False)
    pd.DataFrame([
        {
            **status,
            **{f"empirical_{k}": v for k, v in empirical_summary.items() if k != "family_counts"},
            "empirical_family_counts": str(empirical_summary["family_counts"]),
            **{f"mbl_speed_{k}": v for k, v in mbl_summary.items() if k != "variant_counts"},
            "mbl_speed_variant_counts": str(mbl_summary["variant_counts"]),
        }
    ]).to_csv(status_path, index=False)
    write_report(inventory, best, mbl_speed, power_comparison, empirical_summary, mbl_summary, status, report_path)

    print(f"Wrote {inventory_path}")
    print(f"Wrote {status_path}")
    print(f"Wrote {comparison_path}")
    print(f"Wrote {report_path}")
    print(f"Overall status: {status['overall_status']}")
    print(f"MBL pump type selection complete: {status['mbl_type_selection_complete']}")
    print(f"Next required step: {status['next_required_step']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
