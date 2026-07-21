"""T-1 model gate diagnostic: winner capture vs noise admission.

Pulls top-50% of T-1 OOS candidates across 2024-2026, runs baseline
policy per trade, bucketizes outcomes, and reports retention curves at
various Stage-1 gates (top 1/2/5/10/20/30/50%).

Output answers:
  1. Is the model filtering out bad V_A-confirmed trades, or good ones?
  2. Can we raise the V_A-confirm rate without losing big winners?
  3. What gate maximizes winner capture / noise admission ratio?

Cohort definitions:
  VA-confirm + net_pnl >= $400 = BIG winner
  VA-confirm + 0 <= net_pnl < $400 = SMALL winner
  VA-confirm + net_pnl < 0       = LOSER
  No-flip   + net_pnl > 0        = NF winner
  No-flip   + net_pnl <= 0       = NF loser
"""
from __future__ import annotations
import os, sys, time, gc
from pathlib import Path

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))
os.chdir(project_root)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import numpy as np
import pandas as pd

sys.path.insert(0, str(project_root / "studies" / "v_a_excursion_regime"))
from bracket_2025_2026 import (
    build_schedule, PRE_FLIP_OOS, COLLECTOR_DIR,
    NQ_MULT, COMMISSION_RT,
    replay_va_baseline_1s, replay_no_flip_baseline_1s,
)
from bracket_grid_2024_2025 import (
    load_year_bars_and_flips, apply_roll_filter_year,
)


OUT_DIR = Path("studies/v_a_excursion_regime/results_v0/t1_gate")
GATE_QUANTILES = [0.01, 0.02, 0.05, 0.10, 0.20, 0.30, 0.50]
BIG_WIN_THRESHOLD = 400.0


def replay_year_at_top_q(year, oos_df, threshold):
    """Build schedule + replay baseline policy for one year."""
    print(f"  {year}: building schedule with p_T1 >= {threshold:.4f}...")
    t1 = time.time()
    sched = build_schedule(
        oos_df, year, threshold,
        f"{COLLECTOR_DIR}/v_a_v0_{year}/trades.parquet",
        f"{COLLECTOR_DIR}/v_a_v0_{year}/"
        f"snapshots_with_vol_vwap.parquet")
    n_pre = len(sched)
    sched, n_drop = apply_roll_filter_year(sched, year)
    print(f"    schedule {n_pre:,} → {len(sched):,} after roll-day "
          f"(-{n_drop})  ({time.time()-t1:.0f}s)")

    bar_ts, bar_open, _, _, _, _, _ = load_year_bars_and_flips(year)
    rows = []
    for _, tr in sched.iterrows():
        d = int(tr["direction"])
        if bool(tr["is_va_confirm"]):
            r = replay_va_baseline_1s(
                bar_ts, bar_open,
                int(tr["entry_ts_ns"]),
                int(tr["exit_ts_ns"]), d)
            if r is None:
                continue
            r["is_va_confirm"] = True
        else:
            r = replay_no_flip_baseline_1s(
                bar_ts, bar_open,
                int(tr["entry_ts_ns"]), d)
            if r is None:
                continue
            r["is_va_confirm"] = False
        r["close_ts_ns"] = int(tr["close_ts_ns"])
        r["direction"] = d
        r["p_T1"] = float(tr["p_score"])
        r["year"] = year
        r["pnl_pts"] = (r["exit_fill_price"]
                            - r["entry_fill_price"]) * d
        r["net_pnl"] = r["pnl_pts"] * NQ_MULT - COMMISSION_RT
        rows.append(r)
    df = pd.DataFrame(rows)
    del bar_ts, bar_open
    gc.collect()
    print(f"    {len(df):,} trades replayed  "
          f"({time.time()-t1:.0f}s)")
    return df


def classify(net_pnl, is_va):
    if is_va:
        if net_pnl >= BIG_WIN_THRESHOLD:
            return "VA_big"
        elif net_pnl > 0:
            return "VA_small"
        else:
            return "VA_loser"
    else:
        if net_pnl > 0:
            return "NF_win"
        else:
            return "NF_loss"


def main():
    t0 = time.time()
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    oos = pd.read_parquet(PRE_FLIP_OOS)
    thresholds = {q: oos["p_score"].quantile(1 - q)
                       for q in GATE_QUANTILES}
    top50_thresh = thresholds[0.50]
    print(f"OOS predictions: {len(oos):,}  "
          f"top-50% threshold p_T1 >= {top50_thresh:.4f}")
    print(f"Per-quantile thresholds:")
    for q, t in thresholds.items():
        print(f"  top {q*100:>4.1f}%: p_T1 >= {t:.4f}")

    print(f"\nReplaying baseline policy on top-50% per year...")
    dfs = []
    for year in [2024, 2025, 2026]:
        dfs.append(replay_year_at_top_q(year, oos, top50_thresh))
    all_tr = pd.concat(dfs, ignore_index=True)
    all_tr["bucket"] = all_tr.apply(
        lambda r: classify(r["net_pnl"], r["is_va_confirm"]),
        axis=1)
    all_tr.to_parquet(OUT_DIR / "all_top50_trades.parquet",
                          index=False)
    print(f"  Total trades: {len(all_tr):,}")
    print(f"  Bucket distribution:")
    print(all_tr["bucket"].value_counts())

    # ===== Summary: bucket stats at full top-50% population =====
    print(f"\n{'='*100}")
    print(f"BUCKET STATS — full top-50% population (baseline policy)")
    print(f"{'='*100}")
    print(f"  {'Bucket':<10} {'n':>6} {'%':>6} {'mean':>9} {'sum':>11} "
          f"{'p_T1 mean':>10} {'p_T1 std':>10}")
    for bk in ["VA_big", "VA_small", "VA_loser",
                  "NF_win", "NF_loss"]:
        sub = all_tr[all_tr["bucket"] == bk]
        if len(sub) == 0:
            continue
        print(f"  {bk:<10} {len(sub):>6,} "
              f"{len(sub)/len(all_tr):>5.1%} "
              f"${sub['net_pnl'].mean():>+7.2f} "
              f"${sub['net_pnl'].sum():>+10,.0f} "
              f"{sub['p_T1'].mean():>10.4f} "
              f"{sub['p_T1'].std():>10.4f}")

    # ===== Retention curve =====
    print(f"\n{'='*100}")
    print(f"RETENTION CURVE (by quantile gate, full 3-year)")
    print(f"{'='*100}")
    rows = []
    base_counts = {bk: int((all_tr["bucket"] == bk).sum())
                       for bk in ["VA_big", "VA_small", "VA_loser",
                                    "NF_win", "NF_loss"]}
    for q in GATE_QUANTILES:
        thr = thresholds[q]
        kept = all_tr[all_tr["p_T1"] >= thr]
        row = {"gate_q": q, "thr": thr, "kept": len(kept),
                  "skipped": len(all_tr) - len(kept),
                  "total_net": kept["net_pnl"].sum(),
                  "per_tr": (kept["net_pnl"].mean()
                                if len(kept) else 0)}
        for bk in ["VA_big", "VA_small", "VA_loser",
                      "NF_win", "NF_loss"]:
            sub = kept[kept["bucket"] == bk]
            row[f"{bk}_n"] = len(sub)
            row[f"{bk}_retention"] = (
                len(sub) / base_counts[bk]
                if base_counts[bk] > 0 else 0)
            row[f"{bk}_pnl"] = sub["net_pnl"].sum()
        # Per-year breakdown
        for yr in [2024, 2025, 2026]:
            yr_sub = kept[kept["year"] == yr]
            row[f"y{yr}_n"] = len(yr_sub)
            row[f"y{yr}_total"] = yr_sub["net_pnl"].sum()
            row[f"y{yr}_per_tr"] = (yr_sub["net_pnl"].mean()
                                          if len(yr_sub) else 0)
        rows.append(row)
    summary = pd.DataFrame(rows)
    summary.to_parquet(OUT_DIR / "gate_summary.parquet", index=False)

    # Print retention table
    print(f"\n  Retention rates by bucket")
    print(f"  {'Gate':<8} {'kept':>5} {'VAbig':>7} {'VAsm':>7} "
          f"{'VAloss':>7} {'NFwin':>7} {'NFloss':>7} "
          f"{'tot$':>10} {'$/tr':>8}")
    for _, r in summary.iterrows():
        print(f"  top {r['gate_q']*100:<4.1f}% "
              f"{int(r['kept']):>5} "
              f"{r['VA_big_retention']:>6.1%} "
              f"{r['VA_small_retention']:>6.1%} "
              f"{r['VA_loser_retention']:>6.1%} "
              f"{r['NF_win_retention']:>6.1%} "
              f"{r['NF_loss_retention']:>6.1%} "
              f"${r['total_net']:>+8,.0f} "
              f"${r['per_tr']:>+6.2f}")

    print(f"\n  Counts kept by bucket (in absolute n)")
    print(f"  {'Gate':<8} {'kept':>5} {'VAbig':>6} {'VAsm':>6} "
          f"{'VAloss':>7} {'NFwin':>6} {'NFloss':>7}")
    for _, r in summary.iterrows():
        print(f"  top {r['gate_q']*100:<4.1f}% "
              f"{int(r['kept']):>5} "
              f"{int(r['VA_big_n']):>5} "
              f"{int(r['VA_small_n']):>5} "
              f"{int(r['VA_loser_n']):>6} "
              f"{int(r['NF_win_n']):>5} "
              f"{int(r['NF_loss_n']):>6}")

    print(f"\n  Per-year $/tr at each gate")
    print(f"  {'Gate':<8} {'kept':>5} "
          f"{'2024 n':>6} {'2024 $/tr':>10} "
          f"{'2025 n':>6} {'2025 $/tr':>10} "
          f"{'2026 n':>6} {'2026 $/tr':>10} "
          f"{'min':>9}")
    for _, r in summary.iterrows():
        min_per_tr = min(r["y2024_per_tr"], r["y2025_per_tr"],
                              r["y2026_per_tr"])
        print(f"  top {r['gate_q']*100:<4.1f}% "
              f"{int(r['kept']):>5} "
              f"{int(r['y2024_n']):>5} ${r['y2024_per_tr']:>+7.2f} "
              f"{int(r['y2025_n']):>5} ${r['y2025_per_tr']:>+7.2f} "
              f"{int(r['y2026_n']):>5} ${r['y2026_per_tr']:>+7.2f} "
              f"${min_per_tr:>+6.2f}")

    # ===== Diagnostic: what's the score distribution per bucket? =====
    print(f"\n{'='*100}")
    print(f"P_T1 SCORE DISTRIBUTION BY BUCKET")
    print(f"{'='*100}")
    print(f"  Are big winners getting higher p_T1 scores than losers?")
    print(f"  {'Bucket':<10} {'n':>6} "
          f"{'p25':>9} {'p50':>9} {'p75':>9} {'p90':>9}")
    for bk in ["VA_big", "VA_small", "VA_loser",
                  "NF_win", "NF_loss"]:
        sub = all_tr[all_tr["bucket"] == bk]
        if len(sub) == 0:
            continue
        q = sub["p_T1"].quantile([0.25, 0.5, 0.75, 0.9])
        print(f"  {bk:<10} {len(sub):>6,} "
              f"{q.iloc[0]:>9.4f} {q.iloc[1]:>9.4f} "
              f"{q.iloc[2]:>9.4f} {q.iloc[3]:>9.4f}")

    # ===== Winner capture / noise admission ratio =====
    print(f"\n{'='*100}")
    print(f"WINNER CAPTURE vs NOISE ADMISSION at each gate")
    print(f"{'='*100}")
    print(f"  Capture = VA-big retention (we want HIGH)")
    print(f"  Noise   = NF-loss retention (we want LOW)")
    print(f"  Ratio   = capture / noise  (we want >> 1)")
    print()
    print(f"  {'Gate':<8} {'VAbig kept':>11} {'NFloss kept':>12} "
          f"{'ratio':>7} {'avg$ kept':>11}")
    for _, r in summary.iterrows():
        ratio = (r["VA_big_retention"]
                    / max(r["NF_loss_retention"], 0.0001))
        print(f"  top {r['gate_q']*100:<4.1f}% "
              f"{r['VA_big_retention']:>10.1%} "
              f"{r['NF_loss_retention']:>11.1%} "
              f"{ratio:>7.2f} "
              f"${r['per_tr']:>+8.2f}")

    print(f"\n[done] runtime: {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
