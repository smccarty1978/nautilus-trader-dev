"""Chain-selection audit: why do 1s and tick engines pick different trades?

Hypothesis: a 1m signal bar fires while a prior trade is still open in
tick mode but considered closed in 1s mode (because exits happen at
slightly different times in the two engines), so the 1m signal is
allowed in one engine but blocked in the other.

Methodology:
  Load both trade lists (clean 1-ctr 2025 1s + tick).
  For each trade T in 1s-only set:
    - was tick engine still in a prior trade at T's signal close time?
    - when did the prior trade exit in 1s vs tick?
    - what is T's PnL?
  Same for tick-only trades.

Then test stricter eligibility:
  No new entry if any prior 1s OR tick exit was within last N bars.
"""
from __future__ import annotations
import os, sys
from pathlib import Path
import pandas as pd
import numpy as np

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))
os.chdir(project_root)

OUT = Path("studies/level_momentum_continuation/results_breakout")


def main():
    df_1s = pd.read_parquet(OUT / "nt_v0_2025_clean_1s_trades.parquet")
    df_tk = pd.read_parquet(OUT / "nt_v0_2025_clean_tick_trades.parquet")
    NQ_MULT = 20.0
    print(f"Loaded: 1s={len(df_1s):,}  tick={len(df_tk):,}")

    # Convert ts to pandas Timestamp (UTC)
    df_1s["entry_ts"] = pd.to_datetime(df_1s["c1_fill_ts"], unit="ns",
                                          utc=True)
    df_1s["exit_ts_dt"] = pd.to_datetime(df_1s["exit_ts"], unit="ns",
                                              utc=True)
    df_tk["entry_ts"] = pd.to_datetime(df_tk["c1_fill_ts"], unit="ns",
                                          utc=True)
    df_tk["exit_ts_dt"] = pd.to_datetime(df_tk["exit_ts"], unit="ns",
                                              utc=True)

    # Sort
    df_1s = df_1s.sort_values("entry_ts").reset_index(drop=True)
    df_tk = df_tk.sort_values("entry_ts").reset_index(drop=True)

    # The "signal close time" is the 1m bar close that triggered the
    # entry. Entry happens at the next 1s bar open (1s after signal
    # close). So signal_ts = entry_ts - 1s.
    df_1s["signal_ts"] = df_1s["entry_ts"] - pd.Timedelta(seconds=1)
    df_tk["signal_ts"] = df_tk["entry_ts"] - pd.Timedelta(seconds=1)

    # Match trades: same direction + breach_level + signal_ts within 60s
    merged = pd.merge_asof(
        df_1s.rename(columns={
            "signal_ts": "sig_1s", "entry_ts": "ent_1s",
            "exit_ts_dt": "exit_1s", "c1_pnl_pts": "pnl_1s",
            "exit_reason": "outc_1s", "c1_fill_px": "px_1s",
            "exit_px": "exit_px_1s",
        }),
        df_tk.rename(columns={
            "signal_ts": "sig_tk", "entry_ts": "ent_tk",
            "exit_ts_dt": "exit_tk", "c1_pnl_pts": "pnl_tk",
            "exit_reason": "outc_tk", "c1_fill_px": "px_tk",
            "exit_px": "exit_px_tk",
        }),
        left_on="sig_1s", right_on="sig_tk",
        by=["direction", "breach_level"],
        tolerance=pd.Timedelta(seconds=60),
        direction="nearest",
    )

    matched = merged[merged["sig_tk"].notna()].copy()
    only_1s = merged[merged["sig_tk"].isna()].copy()
    print(f"\nMerge result:")
    print(f"  Matched (in both): {len(matched):,}")
    print(f"  Only-in-1s: {len(only_1s):,}")

    # Find tick trades not in matched
    matched_tk_sigs = matched["sig_tk"].dropna().values
    only_tk = df_tk[~df_tk["signal_ts"].isin(matched_tk_sigs)].copy()
    print(f"  Only-in-tick: {len(only_tk):,}")

    # ----- For 1s-only trades: was tick engine in a prior trade? -----
    print(f"\n{'='*78}")
    print(f"AUDIT: were 1s-only trades blocked by tick chain?")
    print(f"{'='*78}")
    # For each only_1s trade with signal time T:
    # - Find prior tick trade whose entry was BEFORE T but exit was AFTER T
    # - If found, tick engine was busy at T → couldn't take this trade
    tk_entries = df_tk["entry_ts"].values
    tk_exits = df_tk["exit_ts_dt"].values

    blocked_count = 0
    blocked_pnl_pts = 0.0
    not_blocked_count = 0
    not_blocked_pnl_pts = 0.0
    blocking_lag_seconds = []
    for _, row in only_1s.iterrows():
        sig_t = row["sig_1s"].to_datetime64()
        # binary search: rightmost tick entry <= sig_t
        idx = np.searchsorted(tk_entries, sig_t, side="right") - 1
        # walk backwards through prior tick trades
        is_blocked = False
        for j in range(idx, max(idx-5, -1), -1):
            if j < 0: break
            if tk_exits[j] > sig_t:
                # Tick engine was in this trade at sig_t
                is_blocked = True
                # How much later did the tick exit happen vs sig_t?
                lag_secs = (tk_exits[j] - sig_t) / np.timedelta64(1, 's')
                blocking_lag_seconds.append(lag_secs)
                break
        if is_blocked:
            blocked_count += 1
            blocked_pnl_pts += row["pnl_1s"]
        else:
            not_blocked_count += 1
            not_blocked_pnl_pts += row["pnl_1s"]

    n_only_1s = len(only_1s)
    print(f"\nOf {n_only_1s:,} 1s-only trades:")
    print(f"  BLOCKED by tick chain (tick was in prior trade at signal): "
          f"{blocked_count:,} ({100*blocked_count/n_only_1s:.1f}%)")
    print(f"  NOT blocked by tick chain: {not_blocked_count:,} "
          f"({100*not_blocked_count/n_only_1s:.1f}%)")
    print(f"\nPnL of blocked 1s-only trades:")
    print(f"  total: ${blocked_pnl_pts*NQ_MULT:+,.0f}  "
          f"per-trade: ${blocked_pnl_pts*NQ_MULT/max(1,blocked_count):+.2f}")
    print(f"PnL of NOT-blocked 1s-only trades:")
    print(f"  total: ${not_blocked_pnl_pts*NQ_MULT:+,.0f}  "
          f"per-trade: ${not_blocked_pnl_pts*NQ_MULT/max(1,not_blocked_count):+.2f}")

    if blocking_lag_seconds:
        bl = np.array(blocking_lag_seconds)
        print(f"\nBlocking lag (how long tick was still in prior trade past 1s signal):")
        print(f"  median: {np.median(bl):.1f}s  p25/p75: {np.percentile(bl,25):.1f}s/{np.percentile(bl,75):.1f}s  p90: {np.percentile(bl,90):.1f}s")
        print(f"  Distribution:")
        for thr in [1, 5, 10, 30, 60, 120, 300]:
            n = (bl <= thr).sum()
            print(f"    lag <= {thr:>4}s: {n:>4,} ({100*n/len(bl):.1f}%)")

    # ----- Same for tick-only -----
    print(f"\n{'='*78}")
    print(f"AUDIT: were tick-only trades blocked by 1s chain?")
    print(f"{'='*78}")
    s_entries = df_1s["entry_ts"].values
    s_exits = df_1s["exit_ts_dt"].values

    blocked_count_tk = 0; blocked_pnl_tk = 0.0
    not_blocked_count_tk = 0; not_blocked_pnl_tk = 0.0
    for _, row in only_tk.iterrows():
        sig_t = row["signal_ts"].to_datetime64()
        idx = np.searchsorted(s_entries, sig_t, side="right") - 1
        is_blocked = False
        for j in range(idx, max(idx-5, -1), -1):
            if j < 0: break
            if s_exits[j] > sig_t:
                is_blocked = True
                break
        if is_blocked:
            blocked_count_tk += 1
            blocked_pnl_tk += row["c1_pnl_pts"]
        else:
            not_blocked_count_tk += 1
            not_blocked_pnl_tk += row["c1_pnl_pts"]

    n_only_tk = len(only_tk)
    print(f"\nOf {n_only_tk:,} tick-only trades:")
    print(f"  BLOCKED by 1s chain (1s was in prior trade at signal): "
          f"{blocked_count_tk:,} ({100*blocked_count_tk/n_only_tk:.1f}%)")
    print(f"  NOT blocked: {not_blocked_count_tk:,} "
          f"({100*not_blocked_count_tk/n_only_tk:.1f}%)")
    print(f"\nPnL of blocked tick-only trades: total "
          f"${blocked_pnl_tk*NQ_MULT:+,.0f}  per-tr "
          f"${blocked_pnl_tk*NQ_MULT/max(1,blocked_count_tk):+.2f}")
    print(f"PnL of NOT-blocked tick-only: total "
          f"${not_blocked_pnl_tk*NQ_MULT:+,.0f}  per-tr "
          f"${not_blocked_pnl_tk*NQ_MULT/max(1,not_blocked_count_tk):+.2f}")

    # ----- The asymmetric PnL of "extra" trades from each engine -----
    print(f"\n{'='*78}")
    print(f"NET EFFECT OF UNMATCHED TRADES")
    print(f"{'='*78}")
    only_1s_total_pnl = float(only_1s["pnl_1s"].sum() * NQ_MULT)
    only_tk_total_pnl = float(only_tk["c1_pnl_pts"].sum() * NQ_MULT)
    print(f"  Total PnL of 1s-only trades:  ${only_1s_total_pnl:+,.0f}  (n={n_only_1s:,})")
    print(f"  Total PnL of tick-only trades: ${only_tk_total_pnl:+,.0f}  (n={n_only_tk:,})")
    print(f"  Per-trade 1s-only:   ${only_1s_total_pnl/max(1,n_only_1s):+.2f}/tr")
    print(f"  Per-trade tick-only: ${only_tk_total_pnl/max(1,n_only_tk):+.2f}/tr")
    print()
    print(f"If 1s-only PnL is much higher than tick-only PnL → 1s engine")
    print(f"got LUCKIER trade selection (chain-selection bias confirmed)")

    # ----- Save unmatched trades for further analysis -----
    only_1s.to_parquet(OUT / "chain_audit_1s_only.parquet")
    only_tk.to_parquet(OUT / "chain_audit_tick_only.parquet")
    print(f"\nsaved: chain_audit_1s_only.parquet, chain_audit_tick_only.parquet")


if __name__ == "__main__":
    main()
