"""No-flip trade-by-trade matcher: live strategy vs schedule-driven
rescore. Answers: is the -$39 -> -$108/tr jump a population effect or
an exit/rescore implementation divergence?

Commission normalized: all PnL reported as GROSS (commission-free) and
as net at $5 RT, so the live ($5 RT) vs schedule ($10 RT) difference
does not contaminate the comparison.

Match key: (entry_ts, direction). Buckets: matched / live-only /
schedule-only. For matched no-flip trades, classify divergence.
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

LIVE = "backtests/pre_flip_live/results"
SCHED = "backtests/pre_flip_T1/results"
NS = 1_000_000_000


def load_live_noflip():
    dfs = []
    for y in [2024, 2025]:
        d = pd.read_parquet(f"{LIVE}/live_{y}/trades.parquet")
        d["year"] = y
        dfs.append(d)
    df = pd.concat(dfs, ignore_index=True)
    df = df[~df["is_va_confirm"]].copy()
    df["entry_ts"] = df["entry_ts"].astype("int64")
    df["exit_ts"] = df["exit_ts"].astype("int64")
    df["hold_s"] = (df["exit_ts"] - df["entry_ts"]) / NS
    # gross is commission-free; net at $5 RT
    df["net5"] = df["gross_pnl"] - 5.0
    return df


def load_sched_noflip():
    dfs = []
    for y in [2024, 2025]:
        d = pd.read_parquet(
            f"{SCHED}/nt_1s_{y}_top10_rescore_top50/trades.parquet")
        d["year"] = y
        dfs.append(d)
    df = pd.concat(dfs, ignore_index=True)
    df = df[df["exit_filled"] & ~df["is_va_confirm"]].copy()
    df["entry_ts"] = df["entry_ts_ns"].astype("int64")
    df["exit_ts"] = df["exit_ts_ns"].astype("int64")
    df["hold_s"] = (df["exit_ts"] - df["entry_ts"]) / NS
    df["net5"] = df["gross_pnl"] - 5.0
    return df


def main():
    live = load_live_noflip()
    sched = load_sched_noflip()
    print(f"Live no-flip trades (2024-25):     {len(live):,}")
    print(f"Schedule no-flip trades (2024-25): {len(sched):,}")
    print(f"\nGROSS PnL (commission-free):")
    print(f"  live:     ${live['gross_pnl'].sum():+,.0f}  "
          f"(${live['gross_pnl'].mean():+.2f}/tr)")
    print(f"  schedule: ${sched['gross_pnl'].sum():+,.0f}  "
          f"(${sched['gross_pnl'].mean():+.2f}/tr)")
    print(f"NET @ $5 RT:")
    print(f"  live:     ${live['net5'].mean():+.2f}/tr")
    print(f"  schedule: ${sched['net5'].mean():+.2f}/tr")

    # Match on (entry_ts, direction)
    live_keys = set(zip(live["entry_ts"], live["direction"]))
    sched_keys = set(zip(sched["entry_ts"], sched["direction"]))
    matched_keys = live_keys & sched_keys
    live["matched"] = [
        (t, d) in sched_keys
        for t, d in zip(live["entry_ts"], live["direction"])]
    sched["matched"] = [
        (t, d) in live_keys
        for t, d in zip(sched["entry_ts"], sched["direction"])]

    print(f"\n{'='*72}")
    print(f"MATCH BREAKDOWN (key = entry_ts + direction)")
    print(f"{'='*72}")
    live_only = live[~live["matched"]]
    sched_only = sched[~sched["matched"]]
    live_m = live[live["matched"]]
    sched_m = sched[sched["matched"]]
    print(f"  matched (in both):  {len(matched_keys):,}")
    print(f"  live-only:          {len(live_only):,}  "
          f"gross ${live_only['gross_pnl'].sum():+,.0f}  "
          f"(${live_only['gross_pnl'].mean():+.2f}/tr)")
    print(f"  schedule-only:      {len(sched_only):,}  "
          f"gross ${sched_only['gross_pnl'].sum():+,.0f}  "
          f"(${sched_only['gross_pnl'].mean():+.2f}/tr)")
    print(f"  matched live gross: ${live_m['gross_pnl'].sum():+,.0f}  "
          f"(${live_m['gross_pnl'].mean():+.2f}/tr)")
    print(f"  matched sched gross:${sched_m['gross_pnl'].sum():+,.0f}  "
          f"(${sched_m['gross_pnl'].mean():+.2f}/tr)")

    # ---- For matched trades: join and diff ----
    sm = sched_m[["entry_ts", "direction", "exit_ts", "hold_s",
                     "gross_pnl", "p_score", "entry_fill_price",
                     "exit_fill_price"]].rename(columns={
        "exit_ts": "s_exit_ts", "hold_s": "s_hold_s",
        "gross_pnl": "s_gross", "p_score": "s_pscore",
        "entry_fill_price": "s_entry_px",
        "exit_fill_price": "s_exit_px"})
    lm = live_m[["entry_ts", "direction", "exit_ts", "hold_s",
                    "gross_pnl", "p_score", "exit_reason",
                    "entry_fill_price", "exit_fill_price"]].rename(
        columns={"exit_ts": "l_exit_ts", "hold_s": "l_hold_s",
                    "gross_pnl": "l_gross", "p_score": "l_pscore",
                    "exit_reason": "l_exit_reason",
                    "entry_fill_price": "l_entry_px",
                    "exit_fill_price": "l_exit_px"})
    j = lm.merge(sm, on=["entry_ts", "direction"], how="inner")
    # Drop duplicate-key collisions (rare)
    j = j.drop_duplicates(subset=["entry_ts", "direction"])
    print(f"\n{'='*72}")
    print(f"MATCHED NO-FLIP — divergence analysis  (n={len(j):,})")
    print(f"{'='*72}")
    j["hold_diff_s"] = j["l_hold_s"] - j["s_hold_s"]
    j["gross_diff"] = j["l_gross"] - j["s_gross"]
    j["entry_px_diff"] = j["l_entry_px"] - j["s_entry_px"]
    print(f"  live gross:  ${j['l_gross'].sum():+,.0f}  "
          f"(${j['l_gross'].mean():+.2f}/tr)")
    print(f"  sched gross: ${j['s_gross'].sum():+,.0f}  "
          f"(${j['s_gross'].mean():+.2f}/tr)")
    print(f"  gross divergence (live - sched): "
          f"${j['gross_diff'].sum():+,.0f}  "
          f"(${j['gross_diff'].mean():+.2f}/tr)")
    print(f"\n  Hold duration:")
    print(f"    live mean hold:  {j['l_hold_s'].mean():.0f}s")
    print(f"    sched mean hold: {j['s_hold_s'].mean():.0f}s")
    print(f"    hold_diff (live-sched): mean {j['hold_diff_s'].mean():+.0f}s  "
          f"median {j['hold_diff_s'].median():+.0f}s")
    print(f"  Entry price match:")
    print(f"    |entry_px diff| median {j['entry_px_diff'].abs().median():.2f}  "
          f"max {j['entry_px_diff'].abs().max():.2f}")
    print(f"  Entry score (frozen vs walk-forward):")
    print(f"    live p_score  mean {j['l_pscore'].mean():.4f}")
    print(f"    sched p_score mean {j['s_pscore'].mean():.4f}")

    # Divergence buckets
    same_exit = (j["l_exit_ts"] == j["s_exit_ts"])
    live_earlier = (j["l_exit_ts"] < j["s_exit_ts"])
    live_later = (j["l_exit_ts"] > j["s_exit_ts"])
    print(f"\n  Exit-timing divergence (matched trades):")
    for label, m in [("same exit ts      ", same_exit),
                          ("live exited EARLIER", live_earlier),
                          ("live exited LATER  ", live_later)]:
        sub = j[m]
        if len(sub):
            print(f"    {label}: n={len(sub):>5}  "
                  f"({len(sub)/len(j):>5.1%})  "
                  f"live ${sub['l_gross'].mean():+8.2f}/tr  "
                  f"sched ${sub['s_gross'].mean():+8.2f}/tr  "
                  f"diff ${sub['gross_diff'].mean():+8.2f}/tr")

    print(f"\n  Live exit_reason on matched no-flip trades:")
    print(j["l_exit_reason"].value_counts().to_dict())

    # ---- Decomposition: where does the live no-flip loss come from? ----
    print(f"\n{'='*72}")
    print(f"DECOMPOSITION — live no-flip total gross")
    print(f"{'='*72}")
    tot_live = live["gross_pnl"].sum()
    tot_matched_live = live_m["gross_pnl"].sum()
    tot_liveonly = live_only["gross_pnl"].sum()
    print(f"  live no-flip total gross:     ${tot_live:+,.0f}")
    print(f"    from matched trades:        ${tot_matched_live:+,.0f}  "
          f"({len(live_m):,} tr)")
    print(f"    from live-only trades:      ${tot_liveonly:+,.0f}  "
          f"({len(live_only):,} tr)")
    print(f"  schedule no-flip total gross: "
          f"${sched['gross_pnl'].sum():+,.0f}")
    print(f"    from matched trades:        "
          f"${sched_m['gross_pnl'].sum():+,.0f}  ({len(sched_m):,} tr)")
    print(f"    from schedule-only trades:  "
          f"${sched_only['gross_pnl'].sum():+,.0f}  "
          f"({len(sched_only):,} tr)")

    print(f"\n  => On the SAME trades, live vs sched gross/tr: "
          f"${j['l_gross'].mean():+.2f} vs ${j['s_gross'].mean():+.2f}")
    print(f"  => Live-only trades avg gross/tr: "
          f"${live_only['gross_pnl'].mean():+.2f}")
    print(f"  => Schedule-only trades avg gross/tr: "
          f"${sched_only['gross_pnl'].mean():+.2f}")

    j.to_parquet("studies/v_a_excursion_regime/results_v0/"
                    "noflip_matched_diff.parquet", index=False)
    print(f"\nSaved matched diff parquet.")


if __name__ == "__main__":
    main()
