"""Cohen's d for MFE magnitude — big vs small moves.

Two splits:
  Split 1: Top 25% MFE (P75+) vs Bottom 25% (P25-)
  Split 2: MFE >= 2.0 ATR vs MFE < 0.50 ATR

Tests the same 24 features used in the directional study to see if
any feature predicts MAGNITUDE even though none predicted direction.
"""

import sys
import os
from pathlib import Path

project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))
os.chdir(project_root)

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import pandas as pd
import numpy as np


def cohens_d(g1, g2):
    g1 = np.asarray(g1, dtype=np.float64)
    g2 = np.asarray(g2, dtype=np.float64)
    g1 = g1[~np.isnan(g1)]
    g2 = g2[~np.isnan(g2)]
    if len(g1) < 2 or len(g2) < 2:
        return np.nan, np.nan, np.nan
    n1, n2 = len(g1), len(g2)
    m1, m2 = g1.mean(), g2.mean()
    v1, v2 = g1.var(ddof=1), g2.var(ddof=1)
    pooled = np.sqrt(((n1 - 1) * v1 + (n2 - 1) * v2) / (n1 + n2 - 2))
    if pooled == 0:
        return 0.0, m1, m2
    return (m1 - m2) / pooled, m1, m2


def main():
    print("=" * 92)
    print("COHEN'S d — MFE MAGNITUDE (big vs small moves), 6 years")
    print("=" * 92)

    trades = pd.read_parquet(
        "studies/1m_confirmed_flip/results/trades_all.parquet").copy()
    print(f"\n  {len(trades):,} trades")

    mfe = trades["mfe_atr"].values
    print(f"  MFE distribution: "
          f"mean={mfe.mean():.3f}  P25={np.percentile(mfe,25):.3f}  "
          f"P50={np.percentile(mfe,50):.3f}  "
          f"P75={np.percentile(mfe,75):.3f}  "
          f"P90={np.percentile(mfe,90):.3f}")

    # Derived features
    trades["flip_close_dir"] = (
        np.sign(trades["flip_bar_close"] - trades["flip_bar_open"])
        * trades["direction"])
    trades["flip_upper_wick_pct"] = (
        (trades["flip_bar_high"] - np.maximum(
            trades["flip_bar_open"], trades["flip_bar_close"]))
        / trades["flip_bar_range"].replace(0, np.nan))
    trades["flip_lower_wick_pct"] = (
        (np.minimum(trades["flip_bar_open"], trades["flip_bar_close"])
         - trades["flip_bar_low"])
        / trades["flip_bar_range"].replace(0, np.nan))
    trades["range_x_body"] = (trades["flip_bar_range_atr"]
                               * trades["flip_bar_body_pct"])
    trades["vol_x_body"] = (trades["flip_bar_vol_vs_20avg"]
                             * trades["flip_bar_body_pct"])
    trades["dir_x_slope"] = trades["direction"] * trades["ema3_slope"]
    trades["abs_ema_spread"] = trades["ema3_ema9_spread"].abs()

    features = [
        "flip_bar_range_atr", "flip_bar_body_pct", "flip_close_dir",
        "flip_bar_close_location", "flip_upper_wick_pct",
        "flip_lower_wick_pct", "flip_bar_volume", "flip_bar_vol_vs_20avg",
        "direction", "prior_regime_duration_bars", "ema3_slope",
        "ema_spread", "ema3_ema9_spread", "atr_at_flip", "atr_relative",
        "hour_ct", "is_rth", "bar1_range_atr", "bar1_body_pct",
        "bar1_hh_amount_atr",
        "range_x_body", "vol_x_body", "dir_x_slope", "abs_ema_spread",
    ]

    # Split 1: Top vs bottom MFE quartile
    p25 = np.percentile(mfe, 25)
    p75 = np.percentile(mfe, 75)
    big_mask = mfe >= p75
    small_mask = mfe <= p25
    print(f"\n  Split 1: P75={p75:.3f} (big, N={big_mask.sum():,}) vs "
          f"P25={p25:.3f} (small, N={small_mask.sum():,})")

    # Split 2: runners vs duds
    runners_mask = mfe >= 2.0
    duds_mask = mfe < 0.50
    print(f"  Split 2: MFE>=2.0 (runners, N={runners_mask.sum():,}) vs "
          f"MFE<0.50 (duds, N={duds_mask.sum():,})")

    d_table = []
    for f in features:
        vals = trades[f].values.astype(float)
        d1, big_m, sml_m = cohens_d(vals[big_mask], vals[small_mask])
        d2, run_m, dud_m = cohens_d(vals[runners_mask], vals[duds_mask])
        d_table.append({
            "name": f, "d1": d1, "d2": d2,
            "big_m": big_m, "sml_m": sml_m,
            "run_m": run_m, "dud_m": dud_m,
        })

    # Print by max |d|
    d_table.sort(key=lambda r: -max(abs(r["d1"]), abs(r["d2"])))

    print(f"\n{'Feature':<32} {'d(P75/P25)':>12} {'d(2.0/0.50)':>14} "
          f"{'big_m':>10} {'sml_m':>10} {'run_m':>10} {'dud_m':>10}")
    print("-" * 110)
    for r in d_table:
        max_d = max(abs(r["d1"]), abs(r["d2"]))
        flag = " ★" if max_d >= 0.20 else (" ·" if max_d >= 0.15 else "")
        print(f"{r['name']:<32} {r['d1']:>+12.3f} {r['d2']:>+14.3f} "
              f"{r['big_m']:>+10.4f} {r['sml_m']:>+10.4f} "
              f"{r['run_m']:>+10.4f} {r['dud_m']:>+10.4f}{flag}")

    # Quintile analysis for |d| > 0.15 features
    promising = [r for r in d_table
                 if max(abs(r["d1"]), abs(r["d2"])) >= 0.15]
    if promising:
        print(f"\n{'='*92}")
        print(f"QUINTILE ANALYSIS (features with max |d| >= 0.15)")
        print(f"{'='*92}")
        for r in promising:
            vals = trades[r["name"]].values.astype(float)
            df = pd.DataFrame({"v": vals, "mfe": mfe}).dropna()
            if df["v"].nunique() < 5:
                continue
            try:
                df["q"] = pd.qcut(df["v"], q=5, duplicates="drop",
                                   labels=False)
            except ValueError:
                continue
            if df["q"].max() < 4:
                continue
            print(f"\n  Feature: {r['name']} "
                  f"(d P75/P25={r['d1']:+.3f}, d 2.0/0.50={r['d2']:+.3f})")
            print(f"    {'Q':>2} {'Range':>22} {'N':>7} {'Mean MFE':>9} "
                  f"{'Med MFE':>9} {'Reach 2.0%':>10} {'Reach 1.0%':>10}")
            for q in sorted(df["q"].unique()):
                sub = df[df["q"] == q]
                v_lo = sub["v"].min()
                v_hi = sub["v"].max()
                mean_mfe = sub["mfe"].mean()
                med_mfe = sub["mfe"].median()
                reach_2 = (sub["mfe"] >= 2.0).mean() * 100
                reach_1 = (sub["mfe"] >= 1.0).mean() * 100
                print(f"    Q{int(q)+1} [{v_lo:>+8.3f}, {v_hi:>+8.3f}] "
                      f"{len(sub):>6,} {mean_mfe:>8.3f} {med_mfe:>8.3f} "
                      f"{reach_2:>9.1f}% {reach_1:>9.1f}%")
    else:
        print(f"\n  No features with max |d| >= 0.15. "
              f"MFE magnitude is also unpredictable from entry features.")

    print(f"\n{'='*92}")


if __name__ == "__main__":
    main()
