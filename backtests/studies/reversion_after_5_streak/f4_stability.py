"""F4 robustness checks:

  (1) Year-by-year stability of F4 (keep total_exc_fast >= 57.75)
      applied to 2020-2026 bar mode trades. Tests whether the IS-locked
      cutoff produces a positive edge in every calendar year (or only
      mid-period like prior dead branches).

  (2) Cutoff sensitivity scan: test thresholds 40 / 50 / 55 / 57.75
      (IS cutoff) / 60 / 65 / 75 / 90 / 110 pts. Apply each to IS
      (2024-25 bar), OOS bar (2026), OOS tick (2026). Confirm the edge
      isn't razor-thin around the IS cutoff.

Inputs:
  studies/reversion_after_5_streak/results/feature_signals.parquet
  studies/reversion_after_5_streak/results/tick_eod_2026.csv

Outputs:
  studies/reversion_after_5_streak/results/f4_stability_per_year.csv
  studies/reversion_after_5_streak/results/f4_cutoff_sensitivity.csv
"""
from __future__ import annotations
import os, sys
from pathlib import Path

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))
os.chdir(project_root)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import numpy as np
import pandas as pd


NQ_MULT = 20.0
COMMISSION_RT = 5.0
IS_CUTOFF = 57.75   # Q5 threshold from IS 2024-2025
SENSITIVITY_CUTOFFS = [40.0, 50.0, 55.0, 57.75, 60.0, 65.0, 75.0, 90.0, 110.0]
N_BOOT = 1000
RNG_SEED = 42
OUT = Path("studies/reversion_after_5_streak/results")


def bootstrap_mean_ci(arr, n_boot=N_BOOT, seed=RNG_SEED, ci=(0.025, 0.975)):
    if len(arr) < 5:
        return np.nan, np.nan
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(arr), size=(n_boot, len(arr)))
    means = arr[idx].mean(axis=1)
    return float(np.quantile(means, ci[0])), float(np.quantile(means, ci[1]))


def compute_dd(arr):
    if len(arr) == 0: return 0.0
    cum = np.cumsum(arr)
    peak = np.maximum.accumulate(cum)
    return float((cum - peak).min())


def cohort_stats(df, pnl_col, kind_col):
    if len(df) == 0:
        return {"n": 0, "wr_resolved": np.nan, "mean_pnl": np.nan,
                "ci_lo": np.nan, "ci_hi": np.nan,
                "total_pnl": 0.0, "max_dd": 0.0,
                "ci_pos": 0}
    pt = (df[kind_col] == "pt").sum()
    sl = (df[kind_col] == "sl").sum()
    arr = df[pnl_col].to_numpy()
    lo, hi = bootstrap_mean_ci(arr)
    return {
        "n": len(df),
        "wr_resolved": pt / max(pt + sl, 1) * 100,
        "mean_pnl": float(arr.mean()),
        "ci_lo": lo, "ci_hi": hi,
        "ci_pos": int(lo > 0) if np.isfinite(lo) else 0,
        "total_pnl": float(arr.sum()),
        "max_dd": compute_dd(np.array(arr)),
    }


def normalize_exit_kind(df):
    if "exit_kind_bar" in df.columns and "exit_kind" not in df.columns:
        df["exit_kind"] = df["exit_kind_bar"]
    if "exit_reason" in df.columns and "exit_kind" not in df.columns:
        df["exit_kind"] = df["exit_reason"]
    return df


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    feat = pd.read_parquet(OUT / "feature_signals.parquet")
    feat["bar_pnl_dollars"] = feat["bar_outcome_atr"] * feat["atr_at_signal"] * NQ_MULT
    feat = normalize_exit_kind(feat)

    # ---------- (1) Year-by-year stability of F4 ----------
    rows_year = []
    years = sorted(feat["year"].unique())
    print(f"\n=== (1) F4 PER-YEAR STABILITY (cutoff = {IS_CUTOFF}) ===")
    for yr in years:
        sub = feat[feat["year"] == yr].copy()
        kept = sub[sub["total_exc_fast"] >= IS_CUTOFF]
        base_stats = cohort_stats(sub, "bar_pnl_dollars", "exit_kind")
        f4_stats = cohort_stats(kept, "bar_pnl_dollars", "exit_kind")
        rows_year.append({
            "year": yr,
            "n_base": base_stats["n"],
            "n_f4": f4_stats["n"],
            "retention_pct": 100 * f4_stats["n"] / max(base_stats["n"], 1),
            "base_mean": base_stats["mean_pnl"],
            "f4_mean": f4_stats["mean_pnl"],
            "f4_ci_lo": f4_stats["ci_lo"],
            "f4_ci_hi": f4_stats["ci_hi"],
            "f4_ci_pos": f4_stats["ci_pos"],
            "base_wr": base_stats["wr_resolved"],
            "f4_wr": f4_stats["wr_resolved"],
            "base_total": base_stats["total_pnl"],
            "f4_total": f4_stats["total_pnl"],
            "base_max_dd": base_stats["max_dd"],
            "f4_max_dd": f4_stats["max_dd"],
        })

    yr_df = pd.DataFrame(rows_year)
    yr_df.to_csv(OUT / "f4_stability_per_year.csv", index=False)
    with pd.option_context("display.max_columns", None,
                           "display.width", 220,
                           "display.float_format", "{:.2f}".format):
        cols = ["year", "n_base", "n_f4", "retention_pct",
                "base_mean", "f4_mean", "f4_ci_lo", "f4_ci_hi", "f4_ci_pos",
                "base_wr", "f4_wr", "base_total", "f4_total", "f4_max_dd"]
        print(yr_df[cols].to_string(index=False))

    # ---------- (2) Cutoff sensitivity scan ----------
    is_df  = feat[feat["year"].isin([2024, 2025])].copy()
    oos_bar = feat[feat["year"] == 2026].copy()
    tick = pd.read_csv(OUT / "tick_eod_2026.csv")
    tick = tick[tick["exit_reason"] != "no_entry_ticks"].copy()
    tick = normalize_exit_kind(tick)
    oos_tick = tick.merge(
        oos_bar[["signal_ts", "total_exc_fast", "atr_at_signal"]],
        on="signal_ts", how="inner", suffixes=("_t", "_b"))
    # Use tick NET pnl
    if "net_pnl_dollars" not in oos_tick.columns:
        oos_tick["net_pnl_dollars"] = (oos_tick["gross_pnl_dollars"]
                                          - COMMISSION_RT)

    print(f"\n=== (2) CUTOFF SENSITIVITY ({len(SENSITIVITY_CUTOFFS)} thresholds) ===")
    print(f"  IS:  {len(is_df):,} trades, OOS bar: {len(oos_bar):,} trades, "
          f"OOS tick: {len(oos_tick):,} trades")
    rows_cut = []
    for cut in SENSITIVITY_CUTOFFS:
        is_keep = is_df[is_df["total_exc_fast"] >= cut]
        oos_bar_keep = oos_bar[oos_bar["total_exc_fast"] >= cut]
        # Tick: we need to use the FEAT-merged total_exc_fast (right side of suffix)
        # but since suffixes don't apply when the column only appears once,
        # the column kept its original name.
        oos_tick_keep = oos_tick[oos_tick["total_exc_fast"] >= cut]
        row = {"cutoff": cut}
        for label, sub, pnl_col, kind in [
            ("IS_bar", is_keep, "bar_pnl_dollars", "exit_kind"),
            ("OOS_bar", oos_bar_keep, "bar_pnl_dollars", "exit_kind"),
            ("OOS_tick", oos_tick_keep, "net_pnl_dollars", "exit_kind"),
        ]:
            s = cohort_stats(sub, pnl_col, kind)
            row[f"{label}_n"]        = s["n"]
            row[f"{label}_wr"]       = s["wr_resolved"]
            row[f"{label}_mean"]     = s["mean_pnl"]
            row[f"{label}_ci_lo"]    = s["ci_lo"]
            row[f"{label}_ci_hi"]    = s["ci_hi"]
            row[f"{label}_total"]    = s["total_pnl"]
            row[f"{label}_max_dd"]   = s["max_dd"]
        rows_cut.append(row)

    cut_df = pd.DataFrame(rows_cut)
    cut_df.to_csv(OUT / "f4_cutoff_sensitivity.csv", index=False)
    with pd.option_context("display.max_columns", None,
                           "display.width", 240,
                           "display.float_format", "{:.2f}".format):
        cols = ["cutoff",
                "IS_bar_n", "IS_bar_wr", "IS_bar_mean",
                "OOS_bar_n", "OOS_bar_wr", "OOS_bar_mean",
                "OOS_tick_n", "OOS_tick_wr", "OOS_tick_mean",
                "OOS_tick_ci_lo", "OOS_tick_ci_hi",
                "OOS_tick_total", "OOS_tick_max_dd"]
        print(cut_df[cols].to_string(index=False))

    print(f"\nWrote: {OUT/'f4_stability_per_year.csv'}, {OUT/'f4_cutoff_sensitivity.csv'}")


if __name__ == "__main__":
    main()
