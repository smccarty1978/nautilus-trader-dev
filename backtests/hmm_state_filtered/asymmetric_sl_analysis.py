"""Asymmetric PT 2.0 + SL {1.0, 1.25, 1.5} analysis.

The Aug-Oct 2024 long forensic showed:
  - Bad 2024 longs MAE 1.72 ATR vs good 2024 longs MAE 1.64 ATR
  - Bad 2024 longs MFE 1.30 vs good 2024 MFE 1.66
  - Trades reach less favorable, sink further negative
A tighter SL might cap the downside without giving back too much from
trades that eventually reach +2 ATR PT.

But: SL clips winners that pull back before going positive. Open Q is
whether the net (cap losses − clip winners) is favorable on this signal.

Reports:
  [1] Headline: per-year + pooled $/tr by SL level
  [2] Long/short split per SL level (does SL save 2024 longs specifically?)
  [3] Aug-Oct 2024 longs by SL level (does it actually fix the cluster?)
  [4] Exit reason mix per SL level (PT / SL / regime%)
  [5] Year bootstrap stat-significance per SL level
"""
from __future__ import annotations
import os, sys
from pathlib import Path

import numpy as np
import pandas as pd

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))
os.chdir(project_root)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

NQ_MULT = 20.0
COMM = 5.0
RES = Path("backtests/hmm_state_filtered/results")
IS_YEARS = (2020, 2021, 2022)
OOS_YEARS = (2023, 2024, 2025, 2026)
ALL_YEARS = IS_YEARS + OOS_YEARS

SL_LEVELS = [0.0, 1.0, 1.25, 1.5]  # 0.0 = baseline (no SL)
CRASH_MO = ["2024-08", "2024-09", "2024-10"]


def sl_tag(sl):
    """Match the suffix produced by run_backtest.py:
       sl_suffix = f"_sl{args.sl_atr}".replace(".", "p") if args.sl_atr > 0 else ""
    """
    if sl == 0.0:
        return ""
    return f"_sl{sl}".replace(".", "p")


def load_cohort(sl: float) -> pd.DataFrame:
    """Load NT P4 trades with given SL level across all years."""
    rows = []
    for y in ALL_YEARS:
        d = RES / f"nq_hmm_4_s3_pt2p0{sl_tag(sl)}_{y}/trades.parquet"
        if not d.exists():
            continue
        tr = pd.read_parquet(d)
        if not len(tr):
            continue
        tr["year"] = y
        tr["sl_level"] = sl
        tr["pnl_$"] = ((tr["exit_px"] - tr["entry_px"])
                        * tr["signal_direction"] * NQ_MULT - COMM)
        tr["entry_dt"] = pd.to_datetime(tr["entry_ts"])
        tr["month"] = tr["entry_dt"].dt.to_period("M").astype(str)
        rows.append(tr)
    return pd.concat(rows, ignore_index=True) if rows else pd.DataFrame()


def report_headline(cohorts: dict):
    print(f"\n{'='*100}\n  [1] HEADLINE: $/tr per year per SL level\n{'='*100}")
    print(f"  {'year':<6}", end="")
    for sl in SL_LEVELS:
        if sl == 0.0:
            print(f"{'baseline (no SL)':>22}", end="")
        else:
            print(f"{f'SL {sl}':>22}", end="")
    print()
    print(f"  {'':>6}", end="")
    for _ in SL_LEVELS:
        print(f"{'n / $/tr / yr$':>22}", end="")
    print()
    for y in ALL_YEARS:
        marker = " IS" if y in IS_YEARS else "   "
        print(f"  {y:<6}", end="")
        for sl in SL_LEVELS:
            tr = cohorts.get(sl)
            if tr is None or not len(tr):
                print(f"{'-':>22}", end=""); continue
            yr = tr[tr["year"] == y]
            if not len(yr):
                print(f"{'-':>22}", end=""); continue
            print(f"{len(yr):>4} {yr['pnl_$'].mean():>+7.1f} "
                  f"{yr['pnl_$'].sum():>+8.0f}", end="")
        print(f"  {marker}")
    # OOS pool
    print(f"  {'OOS':<6}", end="")
    yrs_pos = []
    for sl in SL_LEVELS:
        tr = cohorts.get(sl)
        if tr is None or not len(tr):
            print(f"{'-':>22}", end=""); yrs_pos.append("?"); continue
        oos = tr[tr["year"].isin(OOS_YEARS)]
        if not len(oos):
            print(f"{'-':>22}", end=""); yrs_pos.append("?"); continue
        yp = sum(1 for yy in OOS_YEARS
                 if (s := oos[oos["year"] == yy])["pnl_$"].mean() > 0 if len(s))
        print(f"{len(oos):>4} {oos['pnl_$'].mean():>+7.1f} "
              f"{oos['pnl_$'].sum():>+8.0f}", end="")
        yrs_pos.append(f"{yp}/4")
    print(f"  POOL")
    print(f"  {'yrs+':<6}", end="")
    for yp in yrs_pos:
        print(f"{yp:>22}", end="")
    print()


def report_long_short(cohorts: dict):
    print(f"\n{'='*100}\n  [2] LONG / SHORT split per SL level\n{'='*100}")
    for side, dir_ in [("LONGS", 1), ("SHORTS", -1)]:
        print(f"\n  {side}:")
        print(f"  {'year':<6}", end="")
        for sl in SL_LEVELS:
            if sl == 0.0:
                print(f"{'baseline':>15}", end="")
            else:
                print(f"{f'SL {sl}':>15}", end="")
        print()
        for y in ALL_YEARS:
            marker = " IS" if y in IS_YEARS else "   "
            print(f"  {y:<6}", end="")
            for sl in SL_LEVELS:
                tr = cohorts.get(sl)
                if tr is None or not len(tr):
                    print(f"{'-':>15}", end=""); continue
                sub = tr[(tr["year"] == y) & (tr["signal_direction"] == dir_)]
                if not len(sub):
                    print(f"{'-':>15}", end=""); continue
                print(f"{len(sub):>4} {sub['pnl_$'].mean():>+9.1f}", end="")
            print(f"  {marker}")
        # OOS pool
        print(f"  {'OOS':<6}", end="")
        for sl in SL_LEVELS:
            tr = cohorts.get(sl)
            if tr is None or not len(tr):
                print(f"{'-':>15}", end=""); continue
            oos = tr[(tr["year"].isin(OOS_YEARS)) & (tr["signal_direction"] == dir_)]
            if not len(oos):
                print(f"{'-':>15}", end=""); continue
            print(f"{len(oos):>4} {oos['pnl_$'].mean():>+9.1f}", end="")
        print(f"  POOL")


def report_aug_oct_2024(cohorts: dict):
    print(f"\n{'='*100}\n  [3] Aug-Oct 2024 LONGS by SL level — does SL save the cluster?\n{'='*100}")
    print(f"  {'SL':<10}{'n':>6}{'WR':>8}{'$/tr':>10}{'total$':>12}"
          f"{'PT%':>8}{'SL%':>8}{'reg%':>8}")
    for sl in SL_LEVELS:
        tr = cohorts.get(sl)
        if tr is None or not len(tr):
            continue
        crash = tr[(tr["year"] == 2024)
                    & (tr["signal_direction"] == 1)
                    & (tr["month"].isin(CRASH_MO))]
        if not len(crash):
            continue
        wr = (crash["pnl_$"] > 0).mean()
        dpt = crash["pnl_$"].mean()
        tot = crash["pnl_$"].sum()
        ex = crash["exit_reason"].value_counts(normalize=True)
        pt_pct = ex.get("PT", 0.0)
        sl_pct = ex.get("stop_loss", 0.0)
        reg_pct = ex.get("regime_flip", 0.0)
        label = "baseline" if sl == 0.0 else f"SL {sl}"
        print(f"  {label:<10}{len(crash):>6}{wr:>7.1%}{dpt:>+10.2f}"
              f"{tot:>+12.0f}{pt_pct:>7.1%}{sl_pct:>7.1%}{reg_pct:>7.1%}")

    print(f"\n  And for comparison — same SL on full year (not just Aug-Oct):")
    print(f"  {'SL':<10}{'n':>6}{'WR':>8}{'$/tr':>10}{'total$':>12}"
          f"{'PT%':>8}{'SL%':>8}{'reg%':>8}")
    for sl in SL_LEVELS:
        tr = cohorts.get(sl)
        if tr is None or not len(tr):
            continue
        full = tr[(tr["year"] == 2024) & (tr["signal_direction"] == 1)]
        if not len(full):
            continue
        wr = (full["pnl_$"] > 0).mean()
        dpt = full["pnl_$"].mean()
        tot = full["pnl_$"].sum()
        ex = full["exit_reason"].value_counts(normalize=True)
        pt_pct = ex.get("PT", 0.0)
        sl_pct = ex.get("stop_loss", 0.0)
        reg_pct = ex.get("regime_flip", 0.0)
        label = "baseline" if sl == 0.0 else f"SL {sl}"
        print(f"  {label:<10}{len(full):>6}{wr:>7.1%}{dpt:>+10.2f}"
              f"{tot:>+12.0f}{pt_pct:>7.1%}{sl_pct:>7.1%}{reg_pct:>7.1%}")

    print(f"\n  And 2025 LONGS — does SL hurt the good year?")
    print(f"  {'SL':<10}{'n':>6}{'WR':>8}{'$/tr':>10}{'total$':>12}"
          f"{'PT%':>8}{'SL%':>8}{'reg%':>8}")
    for sl in SL_LEVELS:
        tr = cohorts.get(sl)
        if tr is None or not len(tr):
            continue
        y25 = tr[(tr["year"] == 2025) & (tr["signal_direction"] == 1)]
        if not len(y25):
            continue
        wr = (y25["pnl_$"] > 0).mean()
        dpt = y25["pnl_$"].mean()
        tot = y25["pnl_$"].sum()
        ex = y25["exit_reason"].value_counts(normalize=True)
        pt_pct = ex.get("PT", 0.0)
        sl_pct = ex.get("stop_loss", 0.0)
        reg_pct = ex.get("regime_flip", 0.0)
        label = "baseline" if sl == 0.0 else f"SL {sl}"
        print(f"  {label:<10}{len(y25):>6}{wr:>7.1%}{dpt:>+10.2f}"
              f"{tot:>+12.0f}{pt_pct:>7.1%}{sl_pct:>7.1%}{reg_pct:>7.1%}")


def report_exit_mix(cohorts: dict):
    print(f"\n{'='*100}\n  [4] Exit-reason mix per SL level (OOS pool)\n{'='*100}")
    print(f"  {'SL':<10}{'n':>7}{'PT%':>8}{'SL%':>8}{'reg%':>8}{'maxh%':>8}"
          f"{'PT_$/tr':>10}{'SL_$/tr':>10}{'reg_$/tr':>10}")
    for sl in SL_LEVELS:
        tr = cohorts.get(sl)
        if tr is None or not len(tr):
            continue
        oos = tr[tr["year"].isin(OOS_YEARS)]
        if not len(oos):
            continue
        ex = oos["exit_reason"].value_counts(normalize=True)
        pt = oos[oos["exit_reason"] == "PT"]
        sls = oos[oos["exit_reason"] == "stop_loss"]
        rg = oos[oos["exit_reason"] == "regime_flip"]
        mh = oos[oos["exit_reason"] == "max_hold"]
        label = "baseline" if sl == 0.0 else f"SL {sl}"
        print(f"  {label:<10}{len(oos):>7}"
              f"{ex.get('PT', 0):>7.1%}{ex.get('stop_loss', 0):>7.1%}"
              f"{ex.get('regime_flip', 0):>7.1%}{ex.get('max_hold', 0):>7.1%}"
              f"{pt['pnl_$'].mean() if len(pt) else float('nan'):>+10.2f}"
              f"{sls['pnl_$'].mean() if len(sls) else float('nan'):>+10.2f}"
              f"{rg['pnl_$'].mean() if len(rg) else float('nan'):>+10.2f}")


def report_bootstrap(cohorts: dict, n_boot: int = 2000):
    print(f"\n{'='*100}\n  [5] YEAR BOOTSTRAP per SL level ({n_boot} resamples, P(<=0))\n{'='*100}")
    print(f"  {'year':<6}", end="")
    for sl in SL_LEVELS:
        label = "baseline" if sl == 0.0 else f"SL {sl}"
        print(f"{label:>22}", end="")
    print()
    print(f"  {'':>6}", end="")
    for _ in SL_LEVELS:
        print(f"{'$/tr / P(<=0)':>22}", end="")
    print()
    rng = np.random.default_rng(42)
    for y in ALL_YEARS:
        marker = " IS" if y in IS_YEARS else "   "
        print(f"  {y:<6}", end="")
        for sl in SL_LEVELS:
            tr = cohorts.get(sl)
            if tr is None or not len(tr):
                print(f"{'-':>22}", end=""); continue
            yr = tr[tr["year"] == y]
            if not len(yr):
                print(f"{'-':>22}", end=""); continue
            pnl = yr["pnl_$"].to_numpy()
            means = np.array([rng.choice(pnl, size=len(pnl), replace=True).mean()
                              for _ in range(n_boot)])
            p_neg = (means <= 0).mean()
            print(f"{pnl.mean():>+9.1f} / {p_neg:>7.1%}", end="")
        print(f" {marker}")


def main():
    print("Loading cohorts (baseline + SL 1.0 / 1.25 / 1.5)...")
    cohorts = {sl: load_cohort(sl) for sl in SL_LEVELS}
    for sl, tr in cohorts.items():
        label = "baseline" if sl == 0.0 else f"SL {sl}"
        if len(tr):
            print(f"  {label}: {len(tr):,} trades across "
                  f"{sorted(tr['year'].unique())}")
        else:
            print(f"  {label}: (no trades — sweep may still be running)")
    print()
    report_headline(cohorts)
    report_long_short(cohorts)
    report_aug_oct_2024(cohorts)
    report_exit_mix(cohorts)
    report_bootstrap(cohorts)


if __name__ == "__main__":
    main()
