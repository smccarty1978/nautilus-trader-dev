"""Population + label-quality diagnostics per gate x year x surface type.

Reads the full-checkpoint and first-eligible-per-regime surfaces
`phase0_prepare_data.py` wrote per (gate, year), and reports the SPEC's
required diagnostics for each.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
WORK, RESULTS = HERE / "_work", HERE / "results"

GATES = ["gate_a_120s", "bridge_180s", "gate_b_240s"]
YEARS = (2021, 2022, 2023, 2024, 2025, 2026)


def summarize(df: pd.DataFrame, gate: str, year: int, surface_type: str) -> dict:
    n = len(df)
    if n == 0:
        return {"gate": gate, "year": year, "surface_type": surface_type, "rows": 0,
                "regimes": 0}
    flipped_300 = df["bearish_flip_within_300s"]
    flipped_600 = df["bearish_flip_within_600s"]
    return {
        "gate": gate, "year": year, "surface_type": surface_type,
        "rows": n, "regimes": int(df["regime_start_ns"].nunique()),
        "median_regime_age_s": float(df["regime_age_s"].median()),
        "median_running_mfe_atr": float(df["running_mfe_atr"].median()),
        "median_retained_mfe_ratio": float(df["retained_mfe_ratio"].median()),
        "bearish_flip_within_300s_rate": float(flipped_300.mean()),
        "bearish_flip_within_600s_rate": float(flipped_600.mean()),
        "followthrough_1A_rate_unconditional_300s": float(
            df["bearish_flip_within_300s_and_followthrough_1A"].mean()),
        "followthrough_1A_rate_unconditional_600s": float(
            df["bearish_flip_within_600s_and_followthrough_1A"].mean()),
        "followthrough_1A_rate_given_flip_300s": (
            float(df.loc[flipped_300, "post_flip_mfe_atr_300s"].ge(1.0).mean())
            if flipped_300.any() else np.nan),
        "followthrough_1A_rate_given_flip_600s": (
            float(df.loc[flipped_600, "post_flip_mfe_atr_600s"].ge(1.0).mean())
            if flipped_600.any() else np.nan),
        "flip_but_no_followthrough_rate": float(df["flip_but_no_followthrough"].mean()),
        "adverse_move_1p25A_before_bearish_flip_rate": float(
            df["adverse_move_1p25A_before_bearish_flip"].mean()),
        "no_flip_before_timeout_rate": float(df["no_flip_before_timeout"].mean()),
        "median_time_to_bearish_flip_s": float(df["time_to_bearish_flip_s"].median()),
        # Policy A outcome labels, diagnostic only.
        "policy_a_opposing_flip_winner_rate": float(df["opposing_flip_exit_positive"].mean()),
        "policy_a_pre_alignment_stop_rate": float(df["hit_pre_alignment_stop"].mean()),
        "policy_a_timeout_rate": float(df["hit_timeout"].mean()),
    }


def main() -> None:
    full_rows, first_rows = [], []
    for gate in GATES:
        for year in YEARS:
            full = pd.read_parquet(WORK / f"full_{gate}_{year}.parquet")
            first = pd.read_parquet(WORK / f"first_eligible_{gate}_{year}.parquet")
            full_rows.append(summarize(full, gate, year, "full_checkpoint"))
            first_rows.append(summarize(first, gate, year, "first_eligible"))

    full_df = pd.DataFrame(full_rows)
    first_df = pd.DataFrame(first_rows)
    full_df.to_csv(RESULTS / "full_checkpoint_surface_summary.csv", index=False)
    first_df.to_csv(RESULTS / "first_eligible_surface_summary.csv", index=False)

    combined = pd.concat([full_df, first_df], ignore_index=True)
    combined[["gate", "year", "surface_type", "rows", "regimes"]].to_csv(
        RESULTS / "gate_population_summary.csv", index=False)
    combined.to_csv(RESULTS / "gate_label_quality_by_year.csv", index=False)

    print(first_df[["gate", "year", "rows", "regimes", "bearish_flip_within_300s_rate",
                    "followthrough_1A_rate_given_flip_300s",
                    "adverse_move_1p25A_before_bearish_flip_rate"]].to_string(index=False))


if __name__ == "__main__":
    main()
