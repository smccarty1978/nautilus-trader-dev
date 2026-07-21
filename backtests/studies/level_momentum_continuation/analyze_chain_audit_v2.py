"""Chain-selection audit V2 — fixed matching + broader chain-state check.

Key fix: when checking if "the OTHER engine was busy", check for ANY
prior trade still open (not just same direction/breach). Chain-blocking
in skip-while-open is per-strategy, not per-instrument-pair.

Also fix the isin bug in V1 (type mismatch).
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
NQ_MULT = 20.0


def main():
    df_1s = pd.read_parquet(OUT / "nt_v0_2025_clean_1s_trades.parquet")
    df_tk = pd.read_parquet(OUT / "nt_v0_2025_clean_tick_trades.parquet")
    print(f"Loaded: 1s={len(df_1s):,}  tick={len(df_tk):,}")

    df_1s["entry_ts"] = pd.to_datetime(df_1s["c1_fill_ts"], unit="ns",
                                          utc=True)
    df_1s["exit_ts_dt"] = pd.to_datetime(df_1s["exit_ts"], unit="ns",
                                              utc=True)
    df_tk["entry_ts"] = pd.to_datetime(df_tk["c1_fill_ts"], unit="ns",
                                          utc=True)
    df_tk["exit_ts_dt"] = pd.to_datetime(df_tk["exit_ts"], unit="ns",
                                              utc=True)
    df_1s["signal_ts"] = df_1s["entry_ts"] - pd.Timedelta(seconds=1)
    df_tk["signal_ts"] = df_tk["entry_ts"] - pd.Timedelta(seconds=1)

    df_1s = df_1s.sort_values("entry_ts").reset_index(drop=True)
    df_tk = df_tk.sort_values("entry_ts").reset_index(drop=True)

    # ---- Match: same trade in both ----
    # Use signal_ts +/- 60s + same direction + same breach_level
    merged = pd.merge_asof(
        df_1s[["signal_ts", "entry_ts", "exit_ts_dt", "c1_pnl_pts",
                "exit_reason", "direction", "breach_level"]]
            .rename(columns={"signal_ts": "sig_1s",
                              "entry_ts": "ent_1s",
                              "exit_ts_dt": "exit_1s",
                              "c1_pnl_pts": "pnl_1s",
                              "exit_reason": "outc_1s"}),
        df_tk[["signal_ts", "entry_ts", "exit_ts_dt", "c1_pnl_pts",
                "exit_reason", "direction", "breach_level"]]
            .rename(columns={"signal_ts": "sig_tk",
                              "entry_ts": "ent_tk",
                              "exit_ts_dt": "exit_tk",
                              "c1_pnl_pts": "pnl_tk",
                              "exit_reason": "outc_tk"}),
        left_on="sig_1s", right_on="sig_tk",
        by=["direction", "breach_level"],
        tolerance=pd.Timedelta(seconds=60),
        direction="nearest",
    )

    matched_mask = merged["sig_tk"].notna()
    matched = merged[matched_mask].copy()
    only_1s = merged[~matched_mask].copy()
    print(f"\nMerge: matched={len(matched):,}  only-1s={len(only_1s):,}")

    # FIX: properly identify only-tick trades.
    # Build a set of sig_tk values that ARE matched
    if len(matched) > 0:
        matched_tk_signals_ns = matched["sig_tk"].astype("int64").values
        df_tk_signals_ns = df_tk["signal_ts"].astype("int64").values
        in_matched = np.isin(df_tk_signals_ns, matched_tk_signals_ns)
        only_tk = df_tk[~in_matched].copy()
    else:
        only_tk = df_tk.copy()
    print(f"  only-tick={len(only_tk):,}")

    # ---- For each unmatched trade, check if OTHER engine was in ANY trade ----
    # Use entry_ts and exit_ts_dt arrays sorted by entry_ts for binary search
    tk_entries = df_tk["entry_ts"].astype("int64").values
    tk_exits = df_tk["exit_ts_dt"].astype("int64").values
    s_entries = df_1s["entry_ts"].astype("int64").values
    s_exits = df_1s["exit_ts_dt"].astype("int64").values

    def was_busy(sig_t_ns, entries_ns, exits_ns, lookback=10):
        """Check if any prior trade was still open at sig_t."""
        idx = np.searchsorted(entries_ns, sig_t_ns, side="right") - 1
        for j in range(idx, max(idx-lookback, -1), -1):
            if j < 0: break
            if exits_ns[j] > sig_t_ns:
                return True, exits_ns[j], j
        return False, None, None

    # Audit only_1s
    print(f"\n{'='*78}")
    print(f"1S-ONLY trades: was tick engine busy at signal time?")
    print(f"{'='*78}")
    blocked = 0; not_blocked = 0
    blocked_pnl = 0.0; not_blocked_pnl = 0.0
    blocking_lags = []
    for _, row in only_1s.iterrows():
        sig_ns = pd.Timestamp(row["sig_1s"]).value
        is_busy, exit_when, _ = was_busy(sig_ns, tk_entries, tk_exits)
        pnl = row["pnl_1s"]
        if is_busy:
            blocked += 1
            blocked_pnl += pnl
            blocking_lags.append((exit_when - sig_ns) / 1e9)  # seconds
        else:
            not_blocked += 1
            not_blocked_pnl += pnl
    n = len(only_1s)
    print(f"  Total 1s-only: {n:,}")
    print(f"  BLOCKED by ANY tick prior trade: {blocked:,} "
          f"({100*blocked/n:.1f}%)  PnL ${blocked_pnl*NQ_MULT:+,.0f}  "
          f"(${blocked_pnl*NQ_MULT/max(1,blocked):+.2f}/tr)")
    print(f"  NOT blocked: {not_blocked:,} ({100*not_blocked/n:.1f}%)  "
          f"PnL ${not_blocked_pnl*NQ_MULT:+,.0f}  "
          f"(${not_blocked_pnl*NQ_MULT/max(1,not_blocked):+.2f}/tr)")
    if blocking_lags:
        bl = np.array(blocking_lags)
        print(f"  Blocking lag (sec past signal): median={np.median(bl):.1f}  "
              f"p75={np.percentile(bl,75):.1f}  p90={np.percentile(bl,90):.1f}")
        for thr in [1, 5, 10, 30, 60, 120, 300, 600]:
            count = (bl <= thr).sum()
            print(f"    lag <= {thr:>4}s: {count:>4,}  "
                  f"({100*count/len(bl):.1f}%)")

    # Audit only_tk
    print(f"\n{'='*78}")
    print(f"TICK-ONLY trades: was 1s engine busy at signal time?")
    print(f"{'='*78}")
    blocked = 0; not_blocked = 0
    blocked_pnl = 0.0; not_blocked_pnl = 0.0
    blocking_lags = []
    for _, row in only_tk.iterrows():
        sig_ns = pd.Timestamp(row["signal_ts"]).value
        is_busy, exit_when, _ = was_busy(sig_ns, s_entries, s_exits)
        pnl = row["c1_pnl_pts"]
        if is_busy:
            blocked += 1
            blocked_pnl += pnl
            blocking_lags.append((exit_when - sig_ns) / 1e9)
        else:
            not_blocked += 1
            not_blocked_pnl += pnl
    n = len(only_tk)
    print(f"  Total tick-only: {n:,}")
    print(f"  BLOCKED by ANY 1s prior trade: {blocked:,} "
          f"({100*blocked/n:.1f}%)  PnL ${blocked_pnl*NQ_MULT:+,.0f}  "
          f"(${blocked_pnl*NQ_MULT/max(1,blocked):+.2f}/tr)")
    print(f"  NOT blocked: {not_blocked:,} ({100*not_blocked/n:.1f}%)  "
          f"PnL ${not_blocked_pnl*NQ_MULT:+,.0f}  "
          f"(${not_blocked_pnl*NQ_MULT/max(1,not_blocked):+.2f}/tr)")
    if blocking_lags:
        bl = np.array(blocking_lags)
        print(f"  Blocking lag: median={np.median(bl):.1f}s  "
              f"p75={np.percentile(bl,75):.1f}s")
        for thr in [1, 5, 10, 30, 60, 120, 300]:
            count = (bl <= thr).sum()
            print(f"    lag <= {thr:>4}s: {count:>4,}  "
                  f"({100*count/len(bl):.1f}%)")

    # ---- Summary ----
    print(f"\n{'='*78}")
    print(f"NET PnL EFFECT")
    print(f"{'='*78}")
    only_1s_total = float(only_1s["pnl_1s"].sum() * NQ_MULT)
    only_tk_total = float(only_tk["c1_pnl_pts"].sum() * NQ_MULT)
    matched_1s_total = float(matched["pnl_1s"].sum() * NQ_MULT)
    matched_tk_total = float(matched["pnl_tk"].sum() * NQ_MULT)
    print(f"  Matched trades:")
    print(f"    1s PnL: ${matched_1s_total:+,.0f}  "
          f"tick PnL: ${matched_tk_total:+,.0f}  "
          f"Δ: ${matched_tk_total-matched_1s_total:+,.0f}")
    print(f"  Only-in-1s trades: PnL ${only_1s_total:+,.0f} "
          f"(n={len(only_1s):,}, ${only_1s_total/max(1,len(only_1s)):+.2f}/tr)")
    print(f"  Only-in-tick trades: PnL ${only_tk_total:+,.0f} "
          f"(n={len(only_tk):,}, ${only_tk_total/max(1,len(only_tk)):+.2f}/tr)")
    print(f"\n  Total: 1s={matched_1s_total + only_1s_total:+,.0f}  "
          f"tick={matched_tk_total + only_tk_total:+,.0f}")
    print(f"  Sanity check (should match log totals):")
    print(f"    1s reported: +$107,425  tick reported: +$7,250")

    # ---- Investigate WHY 91% of 1s-only trades weren't blocked ----
    print(f"\n{'='*78}")
    print(f"DEEP DIVE: 1s-only trades NOT blocked by tick chain — why didn't tick take them?")
    print(f"{'='*78}")
    not_blocked_1s = only_1s.copy()
    # For each, find the nearest tick trade by signal time and see how close
    for _, row in not_blocked_1s.head(5).iterrows():
        sig_ns = pd.Timestamp(row["sig_1s"]).value
        # Find tick trades with signal_ts close (any direction/breach)
        nearby_idx = np.searchsorted(
            df_tk["signal_ts"].astype("int64").values, sig_ns)
        print(f"\n  1s signal: {row['sig_1s']}  dir={row['direction']}  "
              f"L={row['breach_level']:.0f}  outc={row['outc_1s']}  "
              f"pnl_pts={row['pnl_1s']:+.2f}")
        for j in range(max(nearby_idx-2, 0),
                         min(nearby_idx+3, len(df_tk))):
            tk_row = df_tk.iloc[j]
            dt_secs = (pd.Timestamp(tk_row["signal_ts"]).value
                        - sig_ns) / 1e9
            print(f"    nearest tick #{j}: sig={tk_row['signal_ts']}  "
                  f"dt={dt_secs:+.1f}s  dir={tk_row['direction']}  "
                  f"L={tk_row['breach_level']:.0f}  "
                  f"outc={tk_row['exit_reason']}")


if __name__ == "__main__":
    main()
