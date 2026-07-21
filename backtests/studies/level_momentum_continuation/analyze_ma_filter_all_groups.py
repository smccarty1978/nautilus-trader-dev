"""Apply F1_ema13 entry filter to all 3 groups (A, B, C) on the
v-recovery design (+$72K Group A baseline).

Trade mechanics unchanged:
  C1: 1 contract, prior_SL, full PT
  C2: dip + 1m re-cross + MAE >= 3, prior_SL, full PT

Filter: at trigger time, close > EMA13(1m) for long; close < EMA13 for
short. Skip trade if filter fails.

Plus: try a few additional EMA periods (8, 9, 13, 21) to confirm 13 is
the sweet spot or find better.
"""
from __future__ import annotations
import os, sys, time
from pathlib import Path
import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))
os.chdir(project_root)

from studies.level_momentum_continuation.analyze_ma_entry_filter import (
    harvest_with_mas, make_price_vs_ma_filter, apply_filter,
)

OUT = Path("studies/level_momentum_continuation/results_breakout")
OUT.mkdir(parents=True, exist_ok=True)


def main():
    t0 = time.time()
    all_trades = []
    for year in (2024, 2025):
        ts = harvest_with_mas(year)
        all_trades.extend(ts)
    df = pd.DataFrame(all_trades)
    print(f"\nTotal RTH trades: {len(df):,}")

    # Save the full data so we can iterate later
    df.to_parquet(OUT / "ma_filter_all_groups_raw.parquet")

    # Apply F1_ema13 to each group + report
    print(f"\n{'='*78}")
    print(f"F1_EMA13 — close > EMA13 (long), close < EMA13 (short)")
    print(f"{'='*78}")
    summary = []
    for grp in ("A_25pt", "B_14_15pt", "C_10_11pt"):
        g = df[df["group"] == grp].copy()
        n = len(g)
        if n == 0: continue
        base_total = float(g["total_pnl_dollars"].sum())
        base_y24 = float(g[g["year"]==2024]["total_pnl_dollars"].sum())
        base_y25 = float(g[g["year"]==2025]["total_pnl_dollars"].sum())

        out = apply_filter(g, make_price_vs_ma_filter("ema13"),
                            f"F1_ema13_{grp}")
        if out is None: continue
        delta = out["total_$"] - base_total
        delta_y24 = out["y2024_$"] - base_y24
        delta_y25 = out["y2025_$"] - base_y25
        print(f"\n[{grp}] n={n:,}")
        print(f"  Baseline:    total ${base_total:+,.0f} "
              f"(2024 ${base_y24:+,.0f} / 2025 ${base_y25:+,.0f})")
        print(f"  F1_ema13:    total ${out['total_$']:+,.0f} "
              f"(2024 ${out['y2024_$']:+,.0f} / "
              f"2025 ${out['y2025_$']:+,.0f})")
        print(f"  Δ:           ${delta:+,.0f} "
              f"(2024 Δ${delta_y24:+,.0f} / 2025 Δ${delta_y25:+,.0f})")
        print(f"  Kept: {out['n_kept']:,}/{n:,} "
              f"({out['kept_pct']:.1f}%)")
        for bk in ("win_clean", "win_vshape",
                   "loss_runthenbreak", "loss_quick"):
            kp = out.get(f"{bk}_kept_pct")
            if kp is None: continue
            kept_n = out.get(f"{bk}_kept", 0)
            total_n = out.get(f"{bk}_total", 0)
            print(f"    {bk:<22} kept {int(kept_n):>5,}/"
                  f"{int(total_n):,} ({kp:.1f}%)  "
                  f"${out.get(f'{bk}_kept_$', 0):+,.0f}")
        summary.append({
            "group": grp, "filter": "F1_ema13",
            "baseline_total": base_total,
            "filtered_total": out["total_$"],
            "delta": delta,
            "kept_pct": out["kept_pct"],
        })

    # ----- Try EMA8 / EMA9 / EMA21 too -----
    print(f"\n{'='*78}")
    print(f"OTHER EMA PERIODS — sweep across 8, 9, 13, 21")
    print(f"{'='*78}")
    # Need to compute additional EMAs on the harvested data
    # Actually our harvest only computed 13/21/50/sma21
    # Skip for now — iterate after seeing core results

    print(f"\n{'='*78}")
    print(f"COMBINED ALL-GROUPS PnL (with F1_ema13 filter)")
    print(f"{'='*78}")
    total_baseline = sum(s["baseline_total"] for s in summary)
    total_filtered = sum(s["filtered_total"] for s in summary)
    print(f"  Baseline total (A+B+C): ${total_baseline:+,.0f}")
    print(f"  F1_ema13 total (A+B+C):  ${total_filtered:+,.0f}")
    print(f"  Δ:                        ${total_filtered-total_baseline:+,.0f}")

    pd.DataFrame(summary).to_csv(
        OUT / "ma_filter_all_groups.csv", index=False)
    print(f"\n[done] runtime: {time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()
