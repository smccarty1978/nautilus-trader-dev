"""Duration shape analysis (no threshold optimization).

User directive:
  1. Build duration buckets — NO thresholds.
  2. Examine shape of win%, EV, winner size, loser size across buckets.
  3. ONLY OOS data.
  4. Critical mediation test: does state_dur_before EXPLAIN 2025, or
     just describe it? If duration is the mechanism, then WITHIN each
     duration bucket, 2025 vs 2023+2024 should perform similarly.
     If 2025 still outperforms inside every bucket, duration is just
     correlated with the year, not the mechanism.

Buckets (categorical, not optimized):
  0-2, 3-5, 6-10, 11-20, 21+
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

PRODUCT = os.environ.get("PRODUCT", "NQ").upper()
OOS_YEARS = (2023, 2024, 2025, 2026)
PROFITABLE = (2025,)
UNPROFITABLE = (2023, 2024)

BUCKET_EDGES = [0, 3, 6, 11, 21, np.inf]
BUCKET_LABELS = ["0-2", "3-5", "6-10", "11-20", "21+"]


def bucket_dur(d):
    if d < 3:
        return "0-2"
    if d < 6:
        return "3-5"
    if d < 11:
        return "6-10"
    if d < 21:
        return "11-20"
    return "21+"


def summarize_cell(sub):
    if len(sub) == 0:
        return dict(n=0, win=np.nan, mean_atr=np.nan, med_atr=np.nan,
                    win_mean=np.nan, win_med=np.nan,
                    loss_mean=np.nan, loss_med=np.nan,
                    mfe_mean=np.nan, mae_mean=np.nan)
    wins = sub[sub["win"] == 1]
    losses = sub[sub["win"] == 0]
    return dict(
        n=len(sub),
        win=sub["win"].mean(),
        mean_atr=sub["pnl_atr"].mean(),
        med_atr=sub["pnl_atr"].median(),
        win_mean=wins["pnl_atr"].mean() if len(wins) else np.nan,
        win_med=wins["pnl_atr"].median() if len(wins) else np.nan,
        loss_mean=losses["pnl_atr"].mean() if len(losses) else np.nan,
        loss_med=losses["pnl_atr"].median() if len(losses) else np.nan,
        mfe_mean=sub["mfe_atr"].mean(),
        mae_mean=sub["mae_atr"].mean(),
    )


def main():
    p = Path(f"studies/regime_classification/results/"
              f"diagnose_2025_{PRODUCT.lower()}.parquet")
    df = pd.read_parquet(p)
    print(f"Loaded {len(df):,} OOS trades from {p.name}")
    df["dur_bucket"] = df["state_dur_before"].apply(bucket_dur)
    df["dur_bucket"] = pd.Categorical(df["dur_bucket"],
                                        categories=BUCKET_LABELS,
                                        ordered=True)

    # ── 1. Pooled OOS by bucket ──
    print(f"\n{'='*98}\n1. POOLED OOS BY DURATION BUCKET  (no thresholds, just shape)\n{'='*98}")
    print(f"  {'bucket':<8}{'n':>7}{'win%':>8}{'meanATR':>10}{'medATR':>10}"
          f"{'win mean':>10}{'win med':>10}{'loss mean':>11}{'loss med':>10}"
          f"{'MFE mean':>10}{'MAE mean':>10}")
    for b in BUCKET_LABELS:
        s = summarize_cell(df[df["dur_bucket"] == b])
        if s["n"] == 0:
            continue
        print(f"  {b:<8}{s['n']:>7}{s['win']:>7.1%}"
              f"{s['mean_atr']:>+10.3f}{s['med_atr']:>+10.3f}"
              f"{s['win_mean']:>+10.3f}{s['win_med']:>+10.3f}"
              f"{s['loss_mean']:>+11.3f}{s['loss_med']:>+10.3f}"
              f"{s['mfe_mean']:>+10.3f}{s['mae_mean']:>+10.3f}")

    # ── 2. Per-year by bucket (consistency check) ──
    print(f"\n{'='*98}\n2. PER-YEAR by bucket — does the shape repeat?\n{'='*98}")
    print(f"  {'year':<6}{'bucket':<8}{'n':>6}{'win%':>8}{'meanATR':>10}"
          f"{'win mean':>10}{'loss mean':>11}")
    for y in OOS_YEARS:
        yr_df = df[df["year"] == y]
        for b in BUCKET_LABELS:
            s = summarize_cell(yr_df[yr_df["dur_bucket"] == b])
            if s["n"] == 0:
                continue
            print(f"  {y:<6}{b:<8}{s['n']:>6}{s['win']:>7.1%}"
                  f"{s['mean_atr']:>+10.3f}{s['win_mean']:>+10.3f}"
                  f"{s['loss_mean']:>+11.3f}")
        print()

    # ── 3. Year-trade distribution across buckets ──
    print(f"{'='*98}\n3. WHAT FRACTION OF EACH YEAR'S TRADES FALLS IN EACH BUCKET?\n{'='*98}")
    pivot_n = df.pivot_table(index="year", columns="dur_bucket",
                              values="pnl_atr", aggfunc="count",
                              fill_value=0, observed=False)
    pivot_pct = pivot_n.div(pivot_n.sum(axis=1), axis=0) * 100
    print(f"\n  Trade counts:")
    print(pivot_n.to_string())
    print(f"\n  % of year's trades in each bucket:")
    print(pivot_pct.to_string(float_format=lambda x: f"{x:6.1f}%"))

    # ── 4. MEDIATION TEST: within each bucket, 2025 vs 2023+24 ──
    print(f"\n{'='*98}\n4. MEDIATION TEST — within each bucket, "
          f"does PROF (25) vs UNPROF (23+24) gap survive?\n{'='*98}")
    print(f"  If duration is THE mechanism, 2025 inside a bucket should "
          f"resemble 2023+24 inside the same bucket.")
    print(f"  If 2025 still outperforms within every bucket, duration is "
          f"just correlated with year, not the mechanism.\n")
    print(f"  {'bucket':<8}{'group':<14}{'n':>6}{'win%':>8}{'meanATR':>10}"
          f"{'win mean':>10}{'loss mean':>11}")
    for b in BUCKET_LABELS:
        b_df = df[df["dur_bucket"] == b]
        unprof = summarize_cell(b_df[b_df["year"].isin(UNPROFITABLE)])
        prof   = summarize_cell(b_df[b_df["year"].isin(PROFITABLE)])
        if unprof["n"] == 0 and prof["n"] == 0:
            continue
        if unprof["n"] >= 10:
            print(f"  {b:<8}{'UNPROF':<14}{unprof['n']:>6}{unprof['win']:>7.1%}"
                  f"{unprof['mean_atr']:>+10.3f}{unprof['win_mean']:>+10.3f}"
                  f"{unprof['loss_mean']:>+11.3f}")
        if prof["n"] >= 10:
            print(f"  {b:<8}{'PROF (25)':<14}{prof['n']:>6}{prof['win']:>7.1%}"
                  f"{prof['mean_atr']:>+10.3f}{prof['win_mean']:>+10.3f}"
                  f"{prof['loss_mean']:>+11.3f}")
            if unprof["n"] >= 10:
                delta_ev = prof["mean_atr"] - unprof["mean_atr"]
                delta_wm = (prof["win_mean"] - unprof["win_mean"]
                             if not np.isnan(prof["win_mean"]) and
                                 not np.isnan(unprof["win_mean"]) else np.nan)
                delta_lm = (prof["loss_mean"] - unprof["loss_mean"]
                             if not np.isnan(prof["loss_mean"]) and
                                 not np.isnan(unprof["loss_mean"]) else np.nan)
                print(f"  {'':<8}{'    delta':<14}{'':>6}{'':>8}"
                      f"{delta_ev:>+10.3f}{delta_wm:>+10.3f}{delta_lm:>+11.3f}")
        print()

    # ── 5. DECOMPOSITION: how much of 2025's PnL came from each bucket? ──
    print(f"{'='*98}\n5. PnL DECOMPOSITION — where does the year's PnL live?\n{'='*98}")
    print(f"  {'year':<6}{'bucket':<8}{'n':>6}{'sumATR':>10}"
          f"{'% of yr':>10}{'EV/tr':>10}")
    for y in OOS_YEARS:
        yr_df = df[df["year"] == y]
        yr_total = yr_df["pnl_atr"].sum()
        for b in BUCKET_LABELS:
            sub = yr_df[yr_df["dur_bucket"] == b]
            if len(sub) == 0:
                continue
            pnl_sum = sub["pnl_atr"].sum()
            pct = (pnl_sum / yr_total * 100) if yr_total != 0 else 0
            ev = sub["pnl_atr"].mean()
            print(f"  {y:<6}{b:<8}{len(sub):>6}{pnl_sum:>+10.3f}"
                  f"{pct:>9.1f}%{ev:>+10.3f}")
        print()


if __name__ == "__main__":
    main()
