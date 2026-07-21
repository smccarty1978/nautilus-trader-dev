"""Univariate quintile bucket scan over the 20 pre-registered features.

Pre-registered features (per user spec — 5 metrics × 4 windows = 20):
  total_excursion, ratio, net_move, efficiency, close_loc
  × xfast(3m), fast(5m), medium(15m), slow(30m)

For each feature:
  1. Bucket the IS (2024-2025) trades into quintiles by feature value.
  2. Compute per-bucket: n, WR resolved, mean bar PnL ($/trade),
     and the quintile cutoffs (for later OOS application).
  3. Identify monotonic relationships (rank correlation), strong-effect
     buckets (top vs bottom quintile delta), and statistical
     significance via bootstrap CI on per-bucket means.

This is IS-only descriptive analysis. NO OOS data is touched here.
OOS application happens in a follow-up script after we pick winners.

Output:
  studies/reversion_after_5_streak/results/feature_bucket_scan.csv
  studies/reversion_after_5_streak/results/feature_bucket_summary.csv
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
from scipy.stats import spearmanr


NQ_MULT = 20.0
IS_YEARS = [2024, 2025]
N_BOOT = 1000
RNG_SEED = 42
OUT = Path("studies/reversion_after_5_streak/results")

# Pre-registered (per user spec): 5 metrics × 4 windows
METRICS = ["total_exc", "ratio", "net_move", "efficiency", "close_loc"]
WINDOWS = ["xfast", "fast", "medium", "slow"]
FEATURES = [f"{m}_{w}" for m in METRICS for w in WINDOWS]


def bootstrap_mean_ci(arr, n_boot=N_BOOT, seed=RNG_SEED, ci=(0.025, 0.975)):
    if len(arr) < 5:
        return np.nan, np.nan
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(arr), size=(n_boot, len(arr)))
    means = arr[idx].mean(axis=1)
    return float(np.quantile(means, ci[0])), float(np.quantile(means, ci[1]))


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    df = pd.read_parquet(OUT / "feature_signals.parquet")
    df["bar_pnl_dollars"] = df["bar_outcome_atr"] * df["atr_at_signal"] * NQ_MULT
    is_df = df[df["year"].isin(IS_YEARS)].copy()
    n_is = len(is_df)
    print(f"IS sample (2024-2025): {n_is:,} trades")
    print(f"IS overall mean: {is_df['bar_pnl_dollars'].mean():+.2f} $/trade")
    pt_n = int((is_df['exit_kind_bar'] == 'pt').sum())
    sl_n = int((is_df['exit_kind_bar'] == 'sl').sum())
    wr_overall = pt_n / max(pt_n + sl_n, 1) * 100
    print(f"IS overall WR resolved: {wr_overall:.2f}%")
    print()

    rows = []
    summary_rows = []
    is_pnl = is_df["bar_pnl_dollars"].to_numpy()

    for feat in FEATURES:
        if feat not in is_df.columns:
            print(f"  SKIP {feat}: column not present")
            continue
        f_vals = is_df[feat].to_numpy()
        valid_mask = np.isfinite(f_vals)
        if valid_mask.sum() < 100:
            print(f"  SKIP {feat}: too few finite values "
                  f"({valid_mask.sum()})")
            continue

        sub_f = f_vals[valid_mask]
        sub_pnl = is_pnl[valid_mask]
        sub_outcomes = is_df.loc[valid_mask, "exit_kind_bar"].to_numpy()
        n_used = len(sub_f)

        # Spearman rank correlation: monotonic relationship between feat and PnL
        rho, p = spearmanr(sub_f, sub_pnl)

        # Quintile cutoffs
        try:
            qcuts = np.quantile(sub_f, np.linspace(0, 1, 6))
            # Ensure strictly increasing (handle ties); use rank-based binning
            qbin = pd.qcut(sub_f, q=5, labels=False, duplicates="drop")
            n_buckets = int(np.max(qbin) + 1) if qbin is not None else 0
        except Exception as e:
            print(f"  SKIP {feat}: qcut failed: {e}")
            continue

        per_bucket = []
        for b in range(n_buckets):
            mask_b = qbin == b
            sub_b_pnl = sub_pnl[mask_b]
            sub_b_out = sub_outcomes[mask_b]
            if len(sub_b_pnl) == 0:
                continue
            pt_b = (sub_b_out == "pt").sum()
            sl_b = (sub_b_out == "sl").sum()
            eod_b = (sub_b_out == "eod").sum()
            wr_res = pt_b / max(pt_b + sl_b, 1) * 100
            lo, hi = bootstrap_mean_ci(sub_b_pnl)
            row = {
                "feature": feat,
                "bucket": b + 1,
                "n": len(sub_b_pnl),
                "feat_min": float(sub_f[mask_b].min()),
                "feat_max": float(sub_f[mask_b].max()),
                "feat_median": float(np.median(sub_f[mask_b])),
                "pt": pt_b, "sl": sl_b, "eod": eod_b,
                "wr_resolved": wr_res,
                "mean_pnl": float(sub_b_pnl.mean()),
                "ci_lo": lo, "ci_hi": hi,
                "ci_pos": int(lo > 0) if np.isfinite(lo) else 0,
                "ci_neg": int(hi < 0) if np.isfinite(hi) else 0,
            }
            per_bucket.append(row)
            rows.append(row)

        # Summary: top vs bottom delta, spearman, ci sig count
        if len(per_bucket) >= 2:
            top = per_bucket[-1]
            bot = per_bucket[0]
            delta = top["mean_pnl"] - bot["mean_pnl"]
            wr_delta = top["wr_resolved"] - bot["wr_resolved"]
            n_ci_pos = sum(r["ci_pos"] for r in per_bucket)
            n_ci_neg = sum(r["ci_neg"] for r in per_bucket)
            summary_rows.append({
                "feature": feat,
                "n_finite": n_used,
                "spearman_rho": float(rho),
                "spearman_p": float(p),
                "Q5_mean": top["mean_pnl"],
                "Q1_mean": bot["mean_pnl"],
                "Q5_Q1_delta_dollars": delta,
                "Q5_WR_res": top["wr_resolved"],
                "Q1_WR_res": bot["wr_resolved"],
                "Q5_Q1_WR_delta": wr_delta,
                "n_buckets_CI_positive": n_ci_pos,
                "n_buckets_CI_negative": n_ci_neg,
            })

    full = pd.DataFrame(rows)
    summary = pd.DataFrame(summary_rows)
    full.to_csv(OUT / "feature_bucket_scan.csv", index=False)
    summary.to_csv(OUT / "feature_bucket_summary.csv", index=False)

    # Sort summary by |spearman_rho| descending for visibility
    summary_sorted = summary.assign(abs_rho=summary["spearman_rho"].abs()) \
                            .sort_values("abs_rho", ascending=False)

    print("\n=== UNIVARIATE SUMMARY (IS 2024-2025, sorted by |spearman rho|) ===")
    with pd.option_context("display.max_columns", None,
                           "display.width", 220,
                           "display.float_format", "{:.3f}".format):
        cols = ["feature", "n_finite", "spearman_rho", "spearman_p",
                "Q5_mean", "Q1_mean", "Q5_Q1_delta_dollars",
                "Q5_WR_res", "Q1_WR_res", "Q5_Q1_WR_delta",
                "n_buckets_CI_positive", "n_buckets_CI_negative"]
        print(summary_sorted[cols].to_string(index=False))

    # Print quintile detail for the top 5 by |spearman_rho|
    print("\n=== QUINTILE DETAIL FOR TOP 5 BY |SPEARMAN RHO| ===")
    top_feats = summary_sorted.head(5)["feature"].tolist()
    for feat in top_feats:
        feat_buckets = full[full["feature"] == feat].sort_values("bucket")
        print(f"\n--- {feat} ---")
        with pd.option_context("display.max_columns", None,
                               "display.width", 220,
                               "display.float_format", "{:.3f}".format):
            cols = ["bucket", "n", "feat_min", "feat_median", "feat_max",
                    "wr_resolved", "mean_pnl", "ci_lo", "ci_hi", "ci_pos", "ci_neg"]
            print(feat_buckets[cols].to_string(index=False))

    print(f"\nWrote: {OUT/'feature_bucket_scan.csv'}, {OUT/'feature_bucket_summary.csv'}")


if __name__ == "__main__":
    main()
