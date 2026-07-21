"""Drill into REGIME cohort: is it actually positive or skewed by outliers?"""
from __future__ import annotations
import os, sys
from pathlib import Path

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))
os.chdir(project_root)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import numpy as np
import pandas as pd


for year in [2025, 2026]:
    df = pd.read_parquet(
        f"studies/v_a_excursion_regime/results_v0/"
        f"bracket_2years/replay_1s_{year}.parquet")
    nf = df[~df["is_va_confirm"]].copy()
    print("=" * 92)
    print(f"YEAR {year} — no-flip cohort, per-exit-reason breakdown")
    print("=" * 92)
    cols = ["reason", "n", "mean", "median", "std", "WR",
              "p25", "p75", "min", "max"]
    fmt = "{:<10} {:>5} {:>9} {:>9} {:>9} {:>6} {:>9} {:>9} {:>9} {:>9}"
    print(fmt.format(*cols))
    for reason in ["PT", "SL", "TO", "REGIME", "REGIME_NO_OPP"]:
        sub = nf[nf["exit_reason"] == reason]
        if len(sub) == 0:
            continue
        v = sub["net_pnl"]
        print(fmt.format(
            reason, len(sub),
            f"${v.mean():+.2f}", f"${v.median():+.2f}",
            f"${v.std():.2f}", f"{(v>0).mean():.1%}",
            f"${v.quantile(0.25):+.2f}", f"${v.quantile(0.75):+.2f}",
            f"${v.min():+.0f}", f"${v.max():+.0f}"))
    print()

    rg = nf[nf["exit_reason"] == "REGIME"].copy()
    if len(rg) > 0:
        rg["hold_s"] = (rg["exit_ts_ns"] - rg["entry_ts_ns"]) / 1e9
        print(f"  REGIME exits — hold time + PnL distribution")
        print(f"    n={len(rg)}  "
              f"mean_hold={rg['hold_s'].mean():.0f}s  "
              f"median_hold={rg['hold_s'].median():.0f}s  "
              f"WR={(rg['net_pnl']>0).mean():.1%}")
        print(f"    Hold buckets:")
        print(f"      <2 min  : {(rg['hold_s']<120).mean():>5.1%}")
        print(f"      2-5 min : "
              f"{((rg['hold_s']>=120)&(rg['hold_s']<300)).mean():>5.1%}")
        print(f"      5-15 min: "
              f"{((rg['hold_s']>=300)&(rg['hold_s']<900)).mean():>5.1%}")
        print(f"      15-30 min: "
              f"{((rg['hold_s']>=900)&(rg['hold_s']<1800)).mean():>5.1%}")
        print(f"      >30 min : {(rg['hold_s']>=1800).mean():>5.1%}")
        print()
        # PnL distribution by hold-time bucket
        print(f"    PnL by hold-time bucket:")
        for name, lo, hi in [("<2min", 0, 120),
                                  ("2-5min", 120, 300),
                                  ("5-15min", 300, 900),
                                  ("15-30min", 900, 1800),
                                  (">30min", 1800, 1e9)]:
            sub = rg[(rg["hold_s"] >= lo) & (rg["hold_s"] < hi)]
            if len(sub) == 0:
                continue
            print(f"      {name:<10}: n={len(sub):>4}  "
                  f"mean=${sub['net_pnl'].mean():+.2f}/tr  "
                  f"median=${sub['net_pnl'].median():+.2f}/tr  "
                  f"WR={(sub['net_pnl']>0).mean():>5.1%}")
        # Top winners & losers
        print(f"\n    Top 5 REGIME winners:")
        for _, r in rg.nlargest(5, "net_pnl").iterrows():
            print(f"      hold={r['hold_s']:>5.0f}s  "
                  f"d={int(r['direction']):+d}  "
                  f"pts={r['pnl_pts']:+7.2f}  "
                  f"net=${r['net_pnl']:+7,.0f}  "
                  f"atr={r['atr_at_signal']:.2f}")
        print(f"    Top 5 REGIME losers:")
        for _, r in rg.nsmallest(5, "net_pnl").iterrows():
            print(f"      hold={r['hold_s']:>5.0f}s  "
                  f"d={int(r['direction']):+d}  "
                  f"pts={r['pnl_pts']:+7.2f}  "
                  f"net=${r['net_pnl']:+7,.0f}  "
                  f"atr={r['atr_at_signal']:.2f}")
        # Cumulative — does mean stay positive when top 5/10% removed?
        print(f"\n    Robustness — trim extremes:")
        for trim_q in [0.0, 0.01, 0.05, 0.10]:
            lo = rg["net_pnl"].quantile(trim_q)
            hi = rg["net_pnl"].quantile(1 - trim_q)
            trimmed = rg[(rg["net_pnl"] >= lo)
                            & (rg["net_pnl"] <= hi)]
            print(f"      trim {trim_q*100:>4.1f}%: n={len(trimmed):>4}  "
                  f"mean=${trimmed['net_pnl'].mean():+.2f}/tr  "
                  f"total=${trimmed['net_pnl'].sum():+,.0f}")
    print()
