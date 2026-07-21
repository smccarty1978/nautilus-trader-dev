"""Build top-10% schedules for 2024 and 2025 with baseline (+60s) and
in-trade rescore (top50 threshold) variants. Mirrors the existing 2026
top10 schedules.

Outputs:
  schedule_T1_n20_2024_top10.parquet
  schedule_T1_n20_2024_top10_rescore_top50.parquet
  schedule_T1_n20_2025_top10.parquet
  schedule_T1_n20_2025_top10_rescore_top50.parquet
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

sys.path.insert(0, str(project_root / "studies" / "v_a_excursion_regime"))
from bracket_2025_2026 import (
    build_schedule, PRE_FLIP_OOS, COLLECTOR_DIR,
)
from bracket_grid_2024_2025 import apply_roll_filter_year


OUT_BASE = "backtests/pre_flip_T1/results"
TOP_QUANTILE = 0.10
MAX_HOLD_S = 600
RESCORE_INTERVAL_S = 60
RESCORE_THRESHOLD = 0.0770   # top50 = the winner


def compute_rescored_exit_ts(entry_ts_ns, direction, score_lookup, thr):
    for elapsed_s in range(RESCORE_INTERVAL_S, MAX_HOLD_S + 1,
                                  RESCORE_INTERVAL_S):
        check_ts = entry_ts_ns + elapsed_s * 1_000_000_000
        score = score_lookup.get((int(check_ts), direction), None)
        if score is None or score < thr:
            return check_ts
    return entry_ts_ns + MAX_HOLD_S * 1_000_000_000


def main():
    oos = pd.read_parquet(PRE_FLIP_OOS)
    threshold = oos["p_score"].quantile(1 - TOP_QUANTILE)
    print(f"Top-10% threshold: p_T1 >= {threshold:.4f}")

    # Score lookup for in-trade rescore
    score_lookup = {}
    for _, row in oos.iterrows():
        score_lookup[(int(row["close_ts_ns"]),
                          int(row["direction"]))] = float(row["p_score"])
    print(f"Score lookup: {len(score_lookup):,} entries")

    for year in [2024, 2025]:
        print(f"\n=== Year {year} ===")
        sched = build_schedule(
            oos, year, threshold,
            f"{COLLECTOR_DIR}/v_a_v0_{year}/trades.parquet",
            f"{COLLECTOR_DIR}/v_a_v0_{year}/"
            f"snapshots_with_vol_vwap.parquet")
        sched["entry_ts_ns"] = sched["entry_ts_ns"].astype("int64")
        sched["exit_ts_ns"] = sched["exit_ts_ns"].astype("int64")
        sched["year"] = year
        sched["month"] = pd.to_datetime(
            sched["entry_ts_ns"], unit="ns", utc=True).dt.month
        n_pre = len(sched)
        sched, n_drop = apply_roll_filter_year(sched, year)
        print(f"  schedule {n_pre:,} → {len(sched):,} after roll-day "
              f"(-{n_drop})")
        print(f"  VA-confirm: {sched['is_va_confirm'].mean():.1%}")

        # Save baseline
        keep_cols = ["entry_ts_ns", "exit_ts_ns", "direction",
                        "atr_at_signal", "p_score", "is_va_confirm",
                        "year", "month"]
        sched[keep_cols].to_parquet(
            f"{OUT_BASE}/schedule_T1_n20_{year}_top10.parquet",
            index=False)
        print(f"  saved baseline: "
              f"schedule_T1_n20_{year}_top10.parquet")

        # Build rescore variant
        rescore_sched = sched.copy()
        new_exits = []
        for _, row in rescore_sched.iterrows():
            if row["is_va_confirm"]:
                new_exits.append(int(row["exit_ts_ns"]))
            else:
                new_exits.append(compute_rescored_exit_ts(
                    int(row["entry_ts_ns"]),
                    int(row["direction"]),
                    score_lookup, RESCORE_THRESHOLD))
        rescore_sched["exit_ts_ns"] = new_exits
        rescore_sched["hold_s"] = (
            (rescore_sched["exit_ts_ns"] - rescore_sched["entry_ts_ns"])
            / 1_000_000_000)
        nf = rescore_sched[~rescore_sched["is_va_confirm"]]
        print(f"  rescore top50: NF mean_hold={nf['hold_s'].mean():.0f}s  "
              f"median={nf['hold_s'].median():.0f}s")
        rescore_sched[keep_cols].to_parquet(
            f"{OUT_BASE}/schedule_T1_n20_{year}_top10_"
            f"rescore_top50.parquet", index=False)
        print(f"  saved rescore: "
              f"schedule_T1_n20_{year}_top10_rescore_top50.parquet")


if __name__ == "__main__":
    main()
