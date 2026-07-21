"""Build top-20% T-1 N=20 schedule for 2026 OOS.

Identical to build_n20_schedule.py but uses TOP_QUANTILE=0.20 instead
of 0.10. Reuses existing N=20 OOS predictions.
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
from bracket_2025_2026 import build_schedule, PRE_FLIP_OOS, COLLECTOR_DIR


OUT_PATH = ("backtests/pre_flip_T1/results/"
              "schedule_T1_n20_2026_top20.parquet")

oos = pd.read_parquet(PRE_FLIP_OOS)
threshold = oos["p_score"].quantile(1 - 0.20)
print(f"Top-20% threshold: p_T1 >= {threshold:.4f}")

sched = build_schedule(
    oos, 2026, threshold,
    f"{COLLECTOR_DIR}/v_a_v0_2026/trades.parquet",
    f"{COLLECTOR_DIR}/v_a_v0_2026/snapshots_with_vol_vwap.parquet")
print(f"2026 top-20% schedule: {len(sched):,} trades")
print(f"  VA-confirm rate: {sched['is_va_confirm'].mean():.1%}")
print(f"  Direction split: {sched['direction'].value_counts().to_dict()}")

# Adapt columns to match existing NT strategy's expected schema
# (matches schedule_T1_n20_2026_top10.parquet)
sched["entry_ts_ns"] = sched["entry_ts_ns"].astype("int64")
sched["exit_ts_ns"] = sched["exit_ts_ns"].astype("int64")
sched["entry_dt"] = pd.to_datetime(sched["entry_ts_ns"], unit="ns",
                                          utc=True)
sched["month"] = sched["entry_dt"].dt.month
sched["year"] = 2026
keep_cols = ["entry_ts_ns", "exit_ts_ns", "direction",
                "atr_at_signal", "p_score", "is_va_confirm",
                "year", "month"]
# rename for compatibility if needed
sched = sched[[c for c in keep_cols if c in sched.columns]]
sched.to_parquet(OUT_PATH, index=False)
print(f"\nWrote {OUT_PATH}")
print(f"Per-month: {sched['month'].value_counts().sort_index().to_dict()}")
