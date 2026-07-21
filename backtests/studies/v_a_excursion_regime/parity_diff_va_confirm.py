"""Parity diff: does the live strategy's is_va_confirm match the real
V_A definition (an actual confirmed regime flip)?

For each live-strategy trade in 2024-2025, check whether
(entry_ts + 60s, direction) is in the collector's confirmed-flip set
(the real V_A definition the schedule-driven pipeline used).

Confusion matrix:
  live says VA  & collector confirms  -> true positive
  live says VA  & collector does NOT  -> live OVER-counts (the bug)
  live says no  & collector confirms  -> live under-counts
  live says no  & collector does NOT  -> true negative
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

COLLECTOR = "collectors/collector_v2/results"
LIVE = "backtests/pre_flip_live/results"


def collector_confirmed_set(year):
    """Real V_A confirmed flips: (flip_bar_close_ts, direction)."""
    snap = pd.read_parquet(
        f"{COLLECTOR}/v_a_v0_{year}/snapshots_with_vol_vwap.parquet",
        columns=["kind", "decision_ts", "direction",
                   "confirmed", "session"])
    b1 = snap[(snap["kind"] == "bar1_check")
                  & (snap["session"] == "RTH")].copy()
    conf = b1[b1["confirmed"]].copy()
    conf["flip_bar_close_ts"] = (conf["decision_ts"].astype("int64")
                                       - 61_000_000_000)
    return set(zip(conf["flip_bar_close_ts"].astype("int64"),
                       conf["direction"].astype("int64")))


for year in [2024, 2025]:
    print(f"\n{'='*70}\nYEAR {year}\n{'='*70}")
    live = pd.read_parquet(f"{LIVE}/live_{year}/trades.parquet")
    live["entry_ts"] = live["entry_ts"].astype("int64")
    conf_set = collector_confirmed_set(year)
    print(f"  live trades: {len(live):,}")
    print(f"  collector confirmed flips (RTH): {len(conf_set):,}")

    # The flip bar is entry+60s; match (entry_ts+60s, direction).
    live["flip_key_ts"] = live["entry_ts"] + 60_000_000_000
    live["collector_confirms"] = [
        (int(t), int(d)) in conf_set
        for t, d in zip(live["flip_key_ts"], live["direction"])]
    live["live_says_va"] = live["is_va_confirm"].astype(bool)

    tp = int((live["live_says_va"] & live["collector_confirms"]).sum())
    fp = int((live["live_says_va"] & ~live["collector_confirms"]).sum())
    fn = int((~live["live_says_va"] & live["collector_confirms"]).sum())
    tn = int((~live["live_says_va"] & ~live["collector_confirms"]).sum())
    n = len(live)
    print(f"\n  Confusion (live is_va_confirm vs real collector V_A):")
    print(f"    live=VA  & collector=confirm : {tp:>5}  (true VA)")
    print(f"    live=VA  & collector=NO      : {fp:>5}  "
          f"<- live OVER-counts")
    print(f"    live=no  & collector=confirm : {fn:>5}  "
          f"<- live misses")
    print(f"    live=no  & collector=NO      : {tn:>5}  (true no-flip)")
    print(f"  live VA-confirm rate:      {live['live_says_va'].mean():.1%}")
    print(f"  real collector-VA rate:    "
          f"{live['collector_confirms'].mean():.1%}")
    if (tp + fp) > 0:
        print(f"  live-VA precision (of live's VA calls, "
              f"how many real): {tp/(tp+fp):.1%}")

    # PnL by the FOUR cells — does the over-count cohort lose money?
    print(f"\n  Net PnL by cell:")
    for label, mask in [
        ("live=VA real-VA  ", live["live_says_va"]
            & live["collector_confirms"]),
        ("live=VA NOT-real  ", live["live_says_va"]
            & ~live["collector_confirms"]),
        ("live=no real-VA   ", ~live["live_says_va"]
            & live["collector_confirms"]),
        ("live=no NOT-real  ", ~live["live_says_va"]
            & ~live["collector_confirms"])]:
        sub = live[mask]
        if len(sub):
            print(f"    {label}: n={len(sub):>5}  "
                  f"${sub['net_pnl'].sum():>+9,.0f}  "
                  f"${sub['net_pnl'].mean():>+8.2f}/tr")
