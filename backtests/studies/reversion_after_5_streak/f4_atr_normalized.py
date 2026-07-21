"""F4 with ATR-normalized cutoff.

Hypothesis: the absolute 57.75 pt cutoff on total_exc_fast fails in low-vol
years (2023, 2020) because the threshold doesn't scale with regime volatility.
An ATR-normalized version (`total_exc_fast / atr_at_signal >= X`) should
generalize across vol regimes.

Tests:
  1. Compute the ATR-normalized feature on the existing feature_signals.parquet.
  2. Derive IS Q5 cutoff on 2024-2025 (locked).
  3. Year-by-year application of the locked cutoff (2020-2026).
  4. Cutoff sensitivity scan around the IS cutoff.
  5. OOS tick mode 2026 with the locked cutoff.
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
N_BOOT = 1000
RNG_SEED = 42
SENSITIVITY = [2.5, 3.0, 3.5, 4.0, 4.5, 5.0, 5.5, 6.0, 7.0, 8.0]
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
                "total_pnl": 0.0, "max_dd": 0.0}
    pt = (df[kind_col] == "pt").sum()
    sl = (df[kind_col] == "sl").sum()
    arr = df[pnl_col].to_numpy()
    lo, hi = bootstrap_mean_ci(arr)
    return {
        "n": len(df),
        "wr_resolved": pt / max(pt + sl, 1) * 100,
        "mean_pnl": float(arr.mean()),
        "ci_lo": lo, "ci_hi": hi,
        "total_pnl": float(arr.sum()),
        "max_dd": compute_dd(arr),
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
    # ATR-normalized feature
    feat["tef_norm"] = feat["total_exc_fast"] / feat["atr_at_signal"].replace(0, np.nan)

    # IS cutoff (Q5 boundary on 2024-2025 normalized values)
    is_df = feat[feat["year"].isin([2024, 2025])].copy()
    is_norm = is_df["tef_norm"].dropna().to_numpy()
    is_cutoffs = np.quantile(is_norm, np.linspace(0, 1, 6))
    Q5_cut = float(is_cutoffs[4])  # 80th percentile = start of Q5

    print(f"IS Q5 cutoff on ATR-normalized feature: {Q5_cut:.3f}")
    print(f"IS quintile boundaries: {is_cutoffs}")
    # Also report how this maps in absolute pts for reference
    typical_atr = is_df["atr_at_signal"].median()
    print(f"Typical IS ATR (median): {typical_atr:.2f} pts → "
          f"Q5 cut ≈ {Q5_cut * typical_atr:.1f} pts at median ATR")

    # ---------- (1) Year-by-year with locked cutoff ----------
    print(f"\n=== (1) PER-YEAR STABILITY (ATR-norm cutoff = {Q5_cut:.3f}) ===")
    rows_year = []
    for yr in sorted(feat["year"].unique()):
        sub = feat[feat["year"] == yr].copy()
        kept = sub[sub["tef_norm"] >= Q5_cut]
        base = cohort_stats(sub, "bar_pnl_dollars", "exit_kind")
        f4n = cohort_stats(kept, "bar_pnl_dollars", "exit_kind")
        rows_year.append({
            "year": yr,
            "n_base": base["n"], "n_f4n": f4n["n"],
            "retention_pct": 100 * f4n["n"] / max(base["n"], 1),
            "base_mean": base["mean_pnl"],
            "f4n_mean": f4n["mean_pnl"],
            "f4n_ci_lo": f4n["ci_lo"], "f4n_ci_hi": f4n["ci_hi"],
            "f4n_ci_pos": int(f4n["ci_lo"] > 0) if np.isfinite(f4n["ci_lo"]) else 0,
            "base_wr": base["wr_resolved"],
            "f4n_wr": f4n["wr_resolved"],
            "base_total": base["total_pnl"],
            "f4n_total": f4n["total_pnl"],
            "f4n_max_dd": f4n["max_dd"],
        })

    yr_df = pd.DataFrame(rows_year)
    yr_df.to_csv(OUT / "f4n_per_year.csv", index=False)
    with pd.option_context("display.max_columns", None,
                           "display.width", 220,
                           "display.float_format", "{:.2f}".format):
        cols = ["year", "n_base", "n_f4n", "retention_pct",
                "base_mean", "f4n_mean", "f4n_ci_lo", "f4n_ci_hi", "f4n_ci_pos",
                "base_wr", "f4n_wr", "base_total", "f4n_total", "f4n_max_dd"]
        print(yr_df[cols].to_string(index=False))

    # ---------- (2) Cutoff sensitivity ----------
    oos_bar = feat[feat["year"] == 2026].copy()
    tick = pd.read_csv(OUT / "tick_eod_2026.csv")
    tick = tick[tick["exit_reason"] != "no_entry_ticks"].copy()
    tick = normalize_exit_kind(tick)
    oos_tick = tick.merge(
        oos_bar[["signal_ts", "total_exc_fast", "atr_at_signal", "tef_norm"]],
        on="signal_ts", how="inner", suffixes=("_t", "_b"))
    if "net_pnl_dollars" not in oos_tick.columns:
        oos_tick["net_pnl_dollars"] = (oos_tick["gross_pnl_dollars"]
                                          - COMMISSION_RT)

    print(f"\n=== (2) CUTOFF SENSITIVITY (ATR-normalized) ===")
    rows_cut = []
    for cut in SENSITIVITY:
        is_keep = is_df[is_df["tef_norm"] >= cut]
        oos_bar_keep = oos_bar[oos_bar["tef_norm"] >= cut]
        oos_tick_keep = oos_tick[oos_tick["tef_norm"] >= cut]
        row = {"cutoff_atr": cut}
        for label, sub, pnl_col in [
            ("IS_bar", is_keep, "bar_pnl_dollars"),
            ("OOS_bar", oos_bar_keep, "bar_pnl_dollars"),
            ("OOS_tick", oos_tick_keep, "net_pnl_dollars"),
        ]:
            s = cohort_stats(sub, pnl_col, "exit_kind")
            row[f"{label}_n"]     = s["n"]
            row[f"{label}_wr"]    = s["wr_resolved"]
            row[f"{label}_mean"]  = s["mean_pnl"]
            row[f"{label}_ci_lo"] = s["ci_lo"]
            row[f"{label}_ci_hi"] = s["ci_hi"]
            row[f"{label}_total"] = s["total_pnl"]
            row[f"{label}_max_dd"]= s["max_dd"]
        rows_cut.append(row)

    cut_df = pd.DataFrame(rows_cut)
    cut_df.to_csv(OUT / "f4n_cutoff_sensitivity.csv", index=False)
    with pd.option_context("display.max_columns", None,
                           "display.width", 240,
                           "display.float_format", "{:.2f}".format):
        cols = ["cutoff_atr",
                "IS_bar_n", "IS_bar_wr", "IS_bar_mean",
                "OOS_bar_n", "OOS_bar_wr", "OOS_bar_mean",
                "OOS_tick_n", "OOS_tick_wr", "OOS_tick_mean",
                "OOS_tick_ci_lo", "OOS_tick_ci_hi",
                "OOS_tick_total", "OOS_tick_max_dd"]
        print(cut_df[cols].to_string(index=False))

    # ---------- (3) Direct comparison: ATR-norm vs absolute (locked cutoffs) ----------
    print("\n=== (3) DIRECT COMPARISON: locked cutoffs vs baseline ===")
    abs_cut_pts = 57.75   # F4 absolute (from earlier)
    summary = []
    for label, sub in [("IS 2024-25", is_df),
                        ("OOS bar 2026", oos_bar),
                        ("OOS tick 2026", oos_tick)]:
        pnl_col = "net_pnl_dollars" if "tick" in label.lower() else "bar_pnl_dollars"
        base = cohort_stats(sub, pnl_col, "exit_kind")
        f4_abs = cohort_stats(sub[sub["total_exc_fast"] >= abs_cut_pts],
                              pnl_col, "exit_kind")
        f4_norm = cohort_stats(sub[sub["tef_norm"] >= Q5_cut],
                                pnl_col, "exit_kind")
        summary.append({"cohort": label, "filter": "baseline", **base})
        summary.append({"cohort": label, "filter": f"F4_abs >= {abs_cut_pts}", **f4_abs})
        summary.append({"cohort": label, "filter": f"F4_norm >= {Q5_cut:.3f}", **f4_norm})

    summary_df = pd.DataFrame(summary)
    summary_df.to_csv(OUT / "f4n_comparison.csv", index=False)
    with pd.option_context("display.max_columns", None,
                           "display.width", 240,
                           "display.float_format", "{:.2f}".format):
        cols = ["cohort", "filter", "n", "wr_resolved",
                "mean_pnl", "ci_lo", "ci_hi", "total_pnl", "max_dd"]
        print(summary_df[cols].to_string(index=False))

    print(f"\nWrote: {OUT/'f4n_per_year.csv'}, "
          f"{OUT/'f4n_cutoff_sensitivity.csv'}, "
          f"{OUT/'f4n_comparison.csv'}")


if __name__ == "__main__":
    main()
