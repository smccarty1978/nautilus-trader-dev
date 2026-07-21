"""Investigate the 'NT 1s only' trades on 2025-02-05.
For each phantom trade, show:
  - The 1m bar that triggered it (OHLC, EMA13 if we can get it)
  - The prior trade's exit timestamp in both engines
  - The 1s bar OHLC at signal+1s
  - Why pandas/tick didn't take it
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
DAY = "2025-02-05"
day_start = pd.Timestamp(DAY, tz="UTC")
day_end = day_start + pd.Timedelta(days=1)


def main():
    # Load all three engines, day-filtered
    pa = pd.read_parquet(OUT / "pandas_v0_2025_clean_1s_trades.parquet")
    pa = pa[(pa["entry_ts"] >= day_start) & (pa["entry_ts"] < day_end)].copy()

    ns = pd.read_parquet(OUT / "nt_v0_2025_clean_1s_trades.parquet")
    ns["entry_ts"] = pd.to_datetime(ns["c1_fill_ts"], unit="ns", utc=True)
    ns["exit_ts_dt"] = pd.to_datetime(ns["exit_ts"], unit="ns", utc=True)
    ns = ns[(ns["entry_ts"] >= day_start) & (ns["entry_ts"] < day_end)].copy()

    tk = pd.read_parquet(OUT / "nt_v0_2025_clean_tick_trades.parquet")
    tk["entry_ts"] = pd.to_datetime(tk["c1_fill_ts"], unit="ns", utc=True)
    tk["exit_ts_dt"] = pd.to_datetime(tk["exit_ts"], unit="ns", utc=True)
    tk = tk[(tk["entry_ts"] >= day_start) & (tk["entry_ts"] < day_end)].copy()

    # Load 1s and 1m bars for the day
    df_1s = pd.read_parquet("data/raw/NQ_v0_1s_2025.parquet")
    if df_1s.index.tz is None:
        df_1s.index = df_1s.index.tz_localize("UTC")
    df_1s = df_1s[(df_1s.index >= day_start) & (df_1s.index < day_end)].copy()
    df_1s.index.name = "ts_event"

    # Build 1m from 1s: label='right' closed='right' (so close-time labeled)
    df_1m = df_1s[["open", "high", "low", "close", "volume"]].resample(
        "1min", label="right", closed="right"
    ).agg({"open": "first", "high": "max", "low": "min",
           "close": "last", "volume": "sum"}).dropna()

    # Compute EMA13 on 1m closes
    df_1m["ema13"] = df_1m["close"].ewm(span=13, adjust=False).mean()

    # Sort all engines by entry_ts
    pa = pa.sort_values("entry_ts").reset_index(drop=True)
    ns = ns.sort_values("entry_ts").reset_index(drop=True)
    tk = tk.sort_values("entry_ts").reset_index(drop=True)

    # Build keys: (sig_min_floor, dir, breach_level)
    pa["sig_min"] = pa["signal_ts"].dt.floor("1min")
    ns["sig_min"] = ns["entry_ts"].dt.floor("1min")
    tk["sig_min"] = tk["entry_ts"].dt.floor("1min")
    pa["key"] = list(zip(pa["sig_min"], pa["direction"], pa["breach_level"]))
    ns["key"] = list(zip(ns["sig_min"], ns["direction"], ns["breach_level"]))
    tk["key"] = list(zip(tk["sig_min"], tk["direction"], tk["breach_level"]))

    pa_keys = set(pa["key"])
    tk_keys = set(tk["key"])
    ns_only = ns[~ns["key"].isin(pa_keys) & ~ns["key"].isin(tk_keys)].copy()
    print(f"NT 1s only trades on {DAY}: {len(ns_only)}\n")

    for i, row in ns_only.iterrows():
        sig_min = row["sig_min"]
        di = row["direction"]
        L = row["breach_level"]
        dirs = "LONG" if di == 1 else "SHORT"
        target = row["target"]
        prior_sl = row["prior_sl"]

        print(f"{'='*100}")
        print(f"PHANTOM TRADE: {sig_min.strftime('%H:%M:%S')} {dirs}  breach={L}  target={target}  SL={prior_sl}")
        print(f"  NT 1s entry: {row['entry_ts'].strftime('%H:%M:%S.%f')[:-3]}  px={row['c1_fill_px']}  exit={row['exit_ts_dt'].strftime('%H:%M:%S.%f')[:-3]}  px={row['exit_px']}  outcome={row['exit_reason']}  ${row['c1_pnl_dollars']:+.0f}")

        # 1m bar that triggered: ts_event = sig_min - 60s, ts_close = sig_min
        # Our 1m index is ts_event after resample(label='right')... actually
        # resample with label='right' produces index = right edge. Bar at index
        # sig_min covers (sig_min - 60s, sig_min].
        if sig_min in df_1m.index:
            cur = df_1m.loc[sig_min]
            prev_idx = sig_min - pd.Timedelta(minutes=1)
            prev = df_1m.loc[prev_idx] if prev_idx in df_1m.index else None
            print(f"  1m trigger bar (close at {sig_min.strftime('%H:%M:%S')}):")
            print(f"     O={cur['open']:.2f} H={cur['high']:.2f} L={cur['low']:.2f} "
                  f"C={cur['close']:.2f} EMA13={cur['ema13']:.2f}")
            print(f"  1m prior bar:")
            if prev is not None:
                print(f"     O={prev['open']:.2f} H={prev['high']:.2f} L={prev['low']:.2f} "
                      f"C={prev['close']:.2f} EMA13={prev['ema13']:.2f}")
                # Check trigger conditions
                if di == 1:
                    breach_now = cur['close'] > L
                    breach_prior = prev['close'] <= L  # not yet breached
                    bullish_bar = cur['close'] > cur['open']
                    ema_filter = cur['close'] > cur['ema13']
                else:
                    breach_now = cur['close'] < L
                    breach_prior = prev['close'] >= L
                    bullish_bar = cur['close'] < cur['open']  # bearish bar for short
                    ema_filter = cur['close'] < cur['ema13']
                print(f"  Trigger conditions: breach_now={breach_now}  prev_unbreached={breach_prior}  "
                      f"directional_bar={bullish_bar}  ema_aligned={ema_filter}")

        # 1s bar at entry_ts (ts_event = entry_ts in NT 1s mode)
        # entry_ts is the actual fill ts (typically signal+1s for next-bar fill)
        sig_plus_1 = sig_min + pd.Timedelta(seconds=0)  # 1s bar with ts_event = sig_min
        # The 1s bar at ts_event = sig_min covers [sig_min, sig_min+1)
        if sig_plus_1 in df_1s.index:
            b1s = df_1s.loc[sig_plus_1]
            print(f"  1s entry-window bar (ts_event={sig_plus_1.strftime('%H:%M:%S')}, covers signal->signal+1s):")
            print(f"     O={b1s['open']:.2f} H={b1s['high']:.2f} L={b1s['low']:.2f} "
                  f"C={b1s['close']:.2f} V={b1s['volume']}")

        # Prior trade exit times in both engines
        prior_ns = ns[ns["entry_ts"] < row["entry_ts"]].tail(1)
        prior_tk = tk[tk["entry_ts"] < row["entry_ts"]].tail(1)
        print(f"  Chain state at signal time {sig_min.strftime('%H:%M:%S')}:")
        if len(prior_ns):
            pns = prior_ns.iloc[0]
            ns_busy = pns["exit_ts_dt"] > sig_min
            print(f"     NT 1s prior trade: entry {pns['entry_ts'].strftime('%H:%M:%S.%f')[:-3]} "
                  f"exit {pns['exit_ts_dt'].strftime('%H:%M:%S.%f')[:-3]}  "
                  f"chain_busy_at_signal={ns_busy}")
        if len(prior_tk):
            ptk = prior_tk.iloc[0]
            tk_busy = ptk["exit_ts_dt"] > sig_min
            print(f"     NT tk prior trade: entry {ptk['entry_ts'].strftime('%H:%M:%S.%f')[:-3]} "
                  f"exit {ptk['exit_ts_dt'].strftime('%H:%M:%S.%f')[:-3]}  "
                  f"chain_busy_at_signal={tk_busy}")
        print()

    # Same for "NT 1s missed" trades (pandas+tick took, NT 1s didn't)
    ns_keys = set(ns["key"])
    pa_and_tk_not_ns = pa[pa["key"].isin(tk_keys) & ~pa["key"].isin(ns_keys)].copy()
    print(f"\n\n{'#'*100}")
    print(f"# NT 1s MISSED trades (pandas + tick took): {len(pa_and_tk_not_ns)}")
    print(f"{'#'*100}\n")

    for i, row in pa_and_tk_not_ns.iterrows():
        sig_min = row["sig_min"]
        di = row["direction"]
        L = row["breach_level"]
        dirs = "LONG" if di == 1 else "SHORT"
        print(f"{'='*100}")
        print(f"NT 1s MISSED: {sig_min.strftime('%H:%M:%S')} {dirs}  breach={L}")

        # Find pandas + tk trades for this key
        prow = pa[pa["key"] == row["key"]].iloc[0]
        trow_match = tk[tk["key"] == row["key"]]
        if len(trow_match):
            trow = trow_match.iloc[0]
            print(f"  pandas: entry {prow['entry_ts'].strftime('%H:%M:%S.%f')[:-3]} "
                  f"px={prow['engine_entry_px'] if 'engine_entry_px' in prow else prow['entry_px']}  "
                  f"exit ${prow['pnl_$']:+.0f}")
            print(f"  NT tk:  entry {trow['entry_ts'].strftime('%H:%M:%S.%f')[:-3]} "
                  f"px={trow['c1_fill_px']}  exit "
                  f"{trow['exit_ts_dt'].strftime('%H:%M:%S.%f')[:-3]}  ${trow['c1_pnl_dollars']:+.0f}")

        # Chain state
        prior_ns = ns[ns["entry_ts"] < sig_min + pd.Timedelta(minutes=1)].tail(1)
        if len(prior_ns):
            pns = prior_ns.iloc[0]
            ns_busy = pns["exit_ts_dt"] > sig_min
            print(f"  NT 1s prior trade: entry {pns['entry_ts'].strftime('%H:%M:%S.%f')[:-3]} "
                  f"exit {pns['exit_ts_dt'].strftime('%H:%M:%S.%f')[:-3]}  "
                  f"chain_busy_at_signal={ns_busy}")
        print()


if __name__ == "__main__":
    main()
