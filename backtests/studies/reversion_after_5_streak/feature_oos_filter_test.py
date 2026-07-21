"""Apply IS-derived quintile filters to bar-mode + tick-mode 2026 OOS.

Filter candidates (derived from feature_bucket_scan IS results):
  F1: drop trades where total_exc_slow   in Q5 (top 20% by IS cutoff)
  F2: drop trades where total_exc_medium in Q5
  F3: drop trades where total_exc_xfast  in Q4 (the IS sig-negative bucket)
  F4: KEEP trades where total_exc_fast   in Q5 (very restrictive)
  F5: F1 AND F2 (drop trades in top-quintile of either slow or medium)
  F6: F1 AND F3 (drop noisy 30m AND drop bad xfast Q4)
  F7: F1 AND F4 (drop bad slow Q5 AND require good fast Q5)

Methodology:
  - Quintile cutoffs computed from IS (2024-2025) ONLY. Locked.
  - Same cutoffs applied to:
    a) IS (2024-2025) — confirms filter improves IS expectancy
    b) OOS bar-mode (2026 trades from feature_signals.parquet)
    c) OOS tick-mode (2026 trades from tick_eod_2026.csv, merged by signal_ts)
  - For tick mode, the cohort is the EOD-flatten + single-position by exit_ts
    real-fills version (currently -$1.68/trade NET overall).

NOT in this script:
  - No re-fitting on OOS.
  - No discovery of new filters from OOS data.
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
IS_YEARS = [2024, 2025]
OOS_YEARS = [2026]
N_BOOT = 1000
RNG_SEED = 42
OUT = Path("studies/reversion_after_5_streak/results")


def get_quintile_cutoffs(arr, q=5):
    """Return q+1 cutoff values [min, 20%, 40%, 60%, 80%, max]."""
    finite = arr[np.isfinite(arr)]
    if len(finite) < q:
        return None
    return np.quantile(finite, np.linspace(0, 1, q + 1))


def bucket_of(value, cutoffs):
    """Return bucket index 0..4 (Q1..Q5) for value, or -1 if NaN/no cutoffs."""
    if cutoffs is None or not np.isfinite(value):
        return -1
    # np.searchsorted finds index where value would insert: cutoffs[0]=min, [5]=max
    # For value in (cutoffs[i], cutoffs[i+1]], bucket = i (0-indexed)
    idx = np.searchsorted(cutoffs, value, side="right") - 1
    return int(min(max(idx, 0), 4))


def bootstrap_mean_ci(arr, n_boot=N_BOOT, seed=RNG_SEED, ci=(0.025, 0.975)):
    if len(arr) < 5:
        return np.nan, np.nan
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(arr), size=(n_boot, len(arr)))
    means = arr[idx].mean(axis=1)
    return float(np.quantile(means, ci[0])), float(np.quantile(means, ci[1]))


def compute_dd(net_pnl_arr_sorted):
    """Compute max drawdown given a time-sorted NET PnL array."""
    if len(net_pnl_arr_sorted) == 0:
        return 0.0
    cum = np.cumsum(net_pnl_arr_sorted)
    peak = np.maximum.accumulate(cum)
    dd = cum - peak
    return float(dd.min())


def stats(df, label, pnl_col):
    if len(df) == 0:
        return {"label": label, "n": 0}
    n = len(df)
    pt = (df["exit_kind"] == "pt").sum() if "exit_kind" in df.columns else \
         (df["exit_kind_bar"] == "pt").sum() if "exit_kind_bar" in df.columns else 0
    sl = (df["exit_kind"] == "sl").sum() if "exit_kind" in df.columns else \
         (df["exit_kind_bar"] == "sl").sum() if "exit_kind_bar" in df.columns else 0
    nresolved = pt + sl
    arr = df[pnl_col].to_numpy()
    lo, hi = bootstrap_mean_ci(arr)
    return {
        "label": label,
        "n": n,
        "mean_pnl": float(arr.mean()),
        "wr_resolved": pt / max(nresolved, 1) * 100,
        "ci_lo": lo, "ci_hi": hi,
        "total_pnl": float(arr.sum()),
        "max_dd": compute_dd(arr),
        "best": float(arr.max()),
        "worst": float(arr.min()),
    }


def normalize_exit_kind(df):
    """Both bar-mode and tick-mode CSVs use different column names. Normalize."""
    if "exit_kind_bar" in df.columns:
        df["exit_kind"] = df["exit_kind_bar"]
    elif "exit_reason" in df.columns:
        df["exit_kind"] = df["exit_reason"].map(
            lambda x: "pt" if x == "pt" else ("sl" if x == "sl" else "eod"))
    return df


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    feat = pd.read_parquet(OUT / "feature_signals.parquet")
    feat["bar_pnl_dollars"] = feat["bar_outcome_atr"] * feat["atr_at_signal"] * NQ_MULT
    feat = normalize_exit_kind(feat)

    is_mask  = feat["year"].isin(IS_YEARS)
    oos_mask = feat["year"].isin(OOS_YEARS)
    is_df  = feat[is_mask].copy()
    oos_df = feat[oos_mask].copy()
    print(f"IS  (2024-2025): {len(is_df):,} bar-mode trades, "
          f"baseline mean ${is_df['bar_pnl_dollars'].mean():+.2f}/trade")
    print(f"OOS (2026):      {len(oos_df):,} bar-mode trades, "
          f"baseline mean ${oos_df['bar_pnl_dollars'].mean():+.2f}/trade")

    # === Compute IS-locked cutoffs ===
    cuts = {}
    for col in ["total_exc_slow", "total_exc_medium",
                "total_exc_xfast", "total_exc_fast"]:
        cuts[col] = get_quintile_cutoffs(is_df[col].to_numpy())
        print(f"  cutoffs[{col}] = {cuts[col]}")

    # === Define filter functions (each returns boolean keep-mask) ===
    def f1_drop_slow_q5(df):
        return df["total_exc_slow"].apply(
            lambda v: bucket_of(v, cuts["total_exc_slow"])) < 4

    def f2_drop_medium_q5(df):
        return df["total_exc_medium"].apply(
            lambda v: bucket_of(v, cuts["total_exc_medium"])) < 4

    def f3_drop_xfast_q4(df):
        return df["total_exc_xfast"].apply(
            lambda v: bucket_of(v, cuts["total_exc_xfast"])) != 3

    def f4_keep_fast_q5(df):
        return df["total_exc_fast"].apply(
            lambda v: bucket_of(v, cuts["total_exc_fast"])) == 4

    filters = {
        "baseline (no filter)": lambda df: pd.Series(True, index=df.index),
        "F1 drop total_exc_slow Q5": f1_drop_slow_q5,
        "F2 drop total_exc_medium Q5": f2_drop_medium_q5,
        "F3 drop total_exc_xfast Q4": f3_drop_xfast_q4,
        "F4 keep total_exc_fast Q5 only": f4_keep_fast_q5,
        "F5 F1 AND F2": lambda df: f1_drop_slow_q5(df) & f2_drop_medium_q5(df),
        "F6 F1 AND F3": lambda df: f1_drop_slow_q5(df) & f3_drop_xfast_q4(df),
        "F7 F1 AND F4": lambda df: f1_drop_slow_q5(df) & f4_keep_fast_q5(df),
    }

    # === Apply each filter to IS and OOS bar-mode ===
    rows = []
    for fname, fn in filters.items():
        is_keep = fn(is_df)
        oos_keep = fn(oos_df)
        rows.append({"cohort": "IS bar 2024-25", **stats(
            is_df[is_keep], fname, "bar_pnl_dollars")})
        rows.append({"cohort": "OOS bar 2026",  **stats(
            oos_df[oos_keep], fname, "bar_pnl_dollars")})

    # === Apply each filter to OOS TICK MODE ===
    # Load tick_eod_2026.csv and merge with feature_signals on signal_ts.
    tick = pd.read_csv(OUT / "tick_eod_2026.csv")
    tick = tick[tick["exit_reason"] != "no_entry_ticks"].copy()
    tick = normalize_exit_kind(tick)
    # Tick file has signal_ts column. feat has signal_ts. Inner join.
    feat_2026 = feat[feat["year"] == 2026]
    merged = tick.merge(
        feat_2026[["signal_ts"] + ["total_exc_slow", "total_exc_medium",
                                    "total_exc_xfast", "total_exc_fast"]],
        on="signal_ts", how="inner",
        suffixes=("_tick", "_feat"))
    print(f"  tick-bar merge: {len(merged):,} matched trades "
          f"(tick={len(tick)}, feat_2026={len(feat_2026)})")
    # Tick PnL column already in net_pnl_dollars
    if "net_pnl_dollars" not in merged.columns:
        merged["net_pnl_dollars"] = (merged["gross_pnl_dollars"]
                                       - COMMISSION_RT)

    for fname, fn in filters.items():
        keep = fn(merged)
        rows.append({"cohort": "OOS tick 2026", **stats(
            merged[keep], fname, "net_pnl_dollars")})

    out_df = pd.DataFrame(rows)
    out_df.to_csv(OUT / "feature_oos_filter_test.csv", index=False)

    # === Print results in a wide format ===
    cohorts = ["IS bar 2024-25", "OOS bar 2026", "OOS tick 2026"]
    print("\n=== FILTER COMPARISON ===")
    for cohort in cohorts:
        sub = out_df[out_df["cohort"] == cohort]
        print(f"\n--- {cohort} ---")
        with pd.option_context("display.max_columns", None,
                               "display.width", 220,
                               "display.float_format", "{:.2f}".format):
            cols = ["label", "n", "wr_resolved", "mean_pnl",
                    "ci_lo", "ci_hi", "total_pnl", "max_dd",
                    "worst", "best"]
            print(sub[cols].to_string(index=False))

    print(f"\nWrote: {OUT/'feature_oos_filter_test.csv'}")


if __name__ == "__main__":
    main()
