"""Rewrite top-10% 2026 schedule to use in-trade rescore exit for
no-flip trades.

For each no-flip trade, the new exit_ts is determined by walking
forward in 1m increments and checking the T-1 OOS score at that
bar's close. Holds as long as a same-direction candidate exists with
score >= threshold. Exits at first bar where no candidate exists or
score is below threshold. Max hold 600s.

VA-confirm trades keep their original exit_ts (regime flip end).

Saves one schedule per threshold for NT 1s/MBP-1 comparison.
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


SCHEDULE_IN = "backtests/pre_flip_T1/results/schedule_T1_n20_2026_top10.parquet"
PRE_FLIP_OOS = "studies/v_a_excursion_regime/results_v0/pre_flip_T1_n20_oos.parquet"
MAX_HOLD_S = 600
RESCORE_INTERVAL_S = 60

# Test thresholds (None = "any candidate", treated as -1 sentinel)
THRESHOLDS = {
    "any":    -1.0,          # any candidate exists = hold
    "top50": 0.0770,
    "top30": 0.0886,
    "top20": 0.0923,
    "top10": 0.0991,
}


def compute_rescored_exit_ts(entry_ts_ns, direction, score_lookup,
                                     threshold):
    """Walk forward in 1m increments. Returns new exit_ts (ns)."""
    for elapsed_s in range(RESCORE_INTERVAL_S, MAX_HOLD_S + 1,
                                  RESCORE_INTERVAL_S):
        check_ts = entry_ts_ns + elapsed_s * 1_000_000_000
        score = score_lookup.get((int(check_ts), direction), None)
        if score is None:
            return check_ts
        if score < threshold:
            return check_ts
    # max hold reached
    return entry_ts_ns + MAX_HOLD_S * 1_000_000_000


def main():
    sched = pd.read_parquet(SCHEDULE_IN)
    sched["entry_ts_ns"] = sched["entry_ts_ns"].astype("int64")
    sched["exit_ts_ns"] = sched["exit_ts_ns"].astype("int64")
    print(f"Loaded base schedule: {len(sched):,} trades  "
          f"(VA-confirm: {sched['is_va_confirm'].sum()})")

    oos = pd.read_parquet(PRE_FLIP_OOS)
    score_lookup = {}
    for _, row in oos.iterrows():
        score_lookup[(int(row["close_ts_ns"]),
                          int(row["direction"]))] = float(
            row["p_score"])
    print(f"Score lookup: {len(score_lookup):,} entries")

    nf_mask = ~sched["is_va_confirm"]
    print(f"\nRewriting no-flip exits at {len(THRESHOLDS)} "
          f"thresholds...")
    for label, thr in THRESHOLDS.items():
        new_sched = sched.copy()
        new_exits = []
        for idx, row in new_sched.iterrows():
            if row["is_va_confirm"]:
                new_exits.append(int(row["exit_ts_ns"]))
            else:
                new_exits.append(compute_rescored_exit_ts(
                    int(row["entry_ts_ns"]),
                    int(row["direction"]),
                    score_lookup, thr))
        new_sched["exit_ts_ns"] = new_exits
        new_sched["hold_s"] = (
            (new_sched["exit_ts_ns"] - new_sched["entry_ts_ns"])
            / 1_000_000_000)
        nf = new_sched[~new_sched["is_va_confirm"]]
        out_path = (f"backtests/pre_flip_T1/results/"
                       f"schedule_T1_n20_2026_top10_"
                       f"rescore_{label}.parquet")
        new_sched.to_parquet(out_path, index=False)
        print(f"  {label:<8} thr={thr:.4f}: "
              f"NF mean_hold={nf['hold_s'].mean():.0f}s  "
              f"median={nf['hold_s'].median():.0f}s  "
              f"max={nf['hold_s'].max():.0f}s  "
              f"→ {out_path}")


if __name__ == "__main__":
    main()
