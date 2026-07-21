"""Per-trade comparison of pandas / NT 1s / NT tick on a single day far
from any roll window. 2025-02-05 (Wed, mid-week, far from Mar 21 NQ roll).

Goal: see exactly how the three engines differ on identical 2025 NQ.v.0
data — entry timing, entry price, exit timing, exit price, outcome.

Output: side-by-side table per trade, plus day totals and bar context
for any trades that diverge.
"""
from __future__ import annotations
import os, sys
from pathlib import Path
import pandas as pd
import numpy as np
from datetime import datetime, timezone

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))
os.chdir(project_root)

OUT = Path("studies/level_momentum_continuation/results_breakout")
NQ_MULT = 20.0

DAY = "2025-02-05"
day_start = pd.Timestamp(DAY, tz="UTC")
day_end = day_start + pd.Timedelta(days=1)


def load_pandas() -> pd.DataFrame:
    df = pd.read_parquet(OUT / "pandas_v0_2025_clean_1s_trades.parquet")
    df = df[(df["entry_ts"] >= day_start) & (df["entry_ts"] < day_end)].copy()
    df = df.rename(columns={
        "entry_ts": "engine_entry_ts",
        "entry_px": "engine_entry_px",
        "exit_ts":  "engine_exit_ts",
        "exit_px":  "engine_exit_px",
        "outcome":  "engine_outcome",
        "pnl_$":    "engine_pnl",
    })
    df["engine"] = "pandas"
    return df[[
        "engine", "signal_ts", "direction", "breach_level", "target",
        "prior_sl", "group",
        "engine_entry_ts", "engine_entry_px",
        "engine_exit_ts",  "engine_exit_px",
        "engine_outcome",  "engine_pnl",
    ]]


def load_nt(path: str, label: str) -> pd.DataFrame:
    df = pd.read_parquet(path)
    df["engine_entry_ts"] = pd.to_datetime(df["c1_fill_ts"], unit="ns", utc=True)
    df["engine_exit_ts"]  = pd.to_datetime(df["exit_ts"],   unit="ns", utc=True)
    df = df[(df["engine_entry_ts"] >= day_start) & (df["engine_entry_ts"] < day_end)].copy()
    # Reconstruct signal_ts: NT signals on prior 1m close, fills on next 1s
    # so signal is the 1m close that triggered. Approximate: round entry_ts
    # down to the prior whole minute boundary (1m close).
    df["signal_ts"] = (df["engine_entry_ts"].dt.floor("1min"))
    df = df.rename(columns={
        "c1_fill_px":     "engine_entry_px",
        "exit_px":        "engine_exit_px",
        "exit_reason":    "engine_outcome",
        "c1_pnl_dollars": "engine_pnl",
    })
    df["engine"] = label
    return df[[
        "engine", "signal_ts", "direction", "breach_level", "target",
        "prior_sl", "group",
        "engine_entry_ts", "engine_entry_px",
        "engine_exit_ts",  "engine_exit_px",
        "engine_outcome",  "engine_pnl",
    ]]


def main():
    pa = load_pandas()
    ns = load_nt(OUT / "nt_v0_2025_clean_1s_trades.parquet", "NT_1s")
    tk = load_nt(OUT / "nt_v0_2025_clean_tick_trades.parquet", "NT_tk")

    print(f"=== {DAY} | trades per engine ===")
    print(f"  pandas: {len(pa)}  total ${pa['engine_pnl'].sum():+,.0f}")
    print(f"  NT 1s : {len(ns)}  total ${ns['engine_pnl'].sum():+,.0f}")
    print(f"  NT tk : {len(tk)}  total ${tk['engine_pnl'].sum():+,.0f}")
    print()

    # Build a unified key: (direction, breach_level, signal_minute)
    # NT signal_ts already at 1m floor; pandas signal_ts is also 1m close.
    # For pandas, signal_ts == 1m bar's close-time (= 1m floor for whole minute).
    pa["sig_min"] = pa["signal_ts"].dt.floor("1min")
    ns["sig_min"] = ns["signal_ts"].dt.floor("1min")
    tk["sig_min"] = tk["signal_ts"].dt.floor("1min")

    pa["key"] = list(zip(pa["sig_min"], pa["direction"], pa["breach_level"]))
    ns["key"] = list(zip(ns["sig_min"], ns["direction"], ns["breach_level"]))
    tk["key"] = list(zip(tk["sig_min"], tk["direction"], tk["breach_level"]))

    # Union of all keys, sorted by sig_min
    all_keys = sorted(
        set(pa["key"]) | set(ns["key"]) | set(tk["key"]),
        key=lambda k: (k[0], k[2], k[1]),
    )

    print(f"=== Trade-by-trade (sig_min, dir, L) | {len(all_keys)} unique slots ===\n")
    print(f"{'time':<8} {'dir':>3} {'L':>8} | "
          f"{'pa_ts':<8} {'pa_px':>8} {'pa_xpx':>8} {'pa_o':<5} {'pa$':>5} | "
          f"{'1s_ts':<8} {'1s_px':>8} {'1s_xpx':>8} {'1s_o':<5} {'1s$':>5} | "
          f"{'tk_ts':<8} {'tk_px':>8} {'tk_xpx':>8} {'tk_o':<5} {'tk$':>5}")
    print("-" * 200)

    pa_lk = {k: r for k, r in zip(pa["key"], pa.to_dict("records"))}
    ns_lk = {k: r for k, r in zip(ns["key"], ns.to_dict("records"))}
    tk_lk = {k: r for k, r in zip(tk["key"], tk.to_dict("records"))}

    for k in all_keys:
        sig_min, di, L = k
        tstr = sig_min.strftime("%H:%M:%S")
        dirs = "L" if di == 1 else "S"
        row = f"{tstr:<8} {dirs:>3} {L:>8.0f} | "
        for src in (pa_lk, ns_lk, tk_lk):
            if k in src:
                r = src[k]
                ets = r["engine_entry_ts"].strftime("%H:%M:%S")
                xts = r["engine_exit_ts"].strftime("%H:%M:%S")
                row += (f"{ets:<8} {r['engine_entry_px']:>8.2f} "
                        f"{r['engine_exit_px']:>8.2f} "
                        f"{str(r['engine_outcome'])[:4]:<5} "
                        f"{r['engine_pnl']:>+5.0f} | ")
            else:
                row += f"{'--':<8} {'--':>8} {'--':>8} {'--':<5} {'--':>5} | "
        print(row)

    # Summary diffs
    print()
    print(f"=== Disagreement summary ===")
    only_pa = set(pa["key"]) - set(ns["key"]) - set(tk["key"])
    only_ns = set(ns["key"]) - set(pa["key"]) - set(tk["key"])
    only_tk = set(tk["key"]) - set(pa["key"]) - set(ns["key"])
    pa_and_tk_not_ns = (set(pa["key"]) & set(tk["key"])) - set(ns["key"])
    pa_and_ns_not_tk = (set(pa["key"]) & set(ns["key"])) - set(tk["key"])
    ns_and_tk_not_pa = (set(ns["key"]) & set(tk["key"])) - set(pa["key"])
    all_three = set(pa["key"]) & set(ns["key"]) & set(tk["key"])

    print(f"  trades in all 3 engines:   {len(all_three)}")
    print(f"  pandas+tick (not NT 1s):   {len(pa_and_tk_not_ns)}  <- NT 1s missed")
    print(f"  pandas+NT 1s (not tick):   {len(pa_and_ns_not_tk)}")
    print(f"  NT 1s+tick (not pandas):   {len(ns_and_tk_not_pa)}")
    print(f"  pandas only:               {len(only_pa)}")
    print(f"  NT 1s only:                {len(only_ns)}  <- NT 1s phantom")
    print(f"  NT tick only:              {len(only_tk)}")

    # On all-3 trades, check entry/exit price agreement
    print()
    print(f"=== Entry/exit price agreement on all-3 trades ({len(all_three)}) ===")
    same_e = same_x = 0
    pa_better_entry = ns_better_entry = 0
    diffs_e_pa_vs_ns = []
    diffs_e_pa_vs_tk = []
    diffs_e_ns_vs_tk = []
    for k in all_three:
        rp = pa_lk[k]; rn = ns_lk[k]; rt = tk_lk[k]
        diffs_e_pa_vs_ns.append(rn["engine_entry_px"] - rp["engine_entry_px"])
        diffs_e_pa_vs_tk.append(rt["engine_entry_px"] - rp["engine_entry_px"])
        diffs_e_ns_vs_tk.append(rt["engine_entry_px"] - rn["engine_entry_px"])
    if diffs_e_pa_vs_ns:
        d = np.array(diffs_e_pa_vs_ns)
        print(f"  NT 1s entry - pandas entry:  mean {d.mean():+.3f}  median {np.median(d):+.3f}  abs_max {abs(d).max():.2f}  n0_diff {int(np.sum(d!=0))}/{len(d)}")
        d = np.array(diffs_e_pa_vs_tk)
        print(f"  NT tk entry - pandas entry:  mean {d.mean():+.3f}  median {np.median(d):+.3f}  abs_max {abs(d).max():.2f}  n0_diff {int(np.sum(d!=0))}/{len(d)}")
        d = np.array(diffs_e_ns_vs_tk)
        print(f"  NT tk entry - NT 1s entry:   mean {d.mean():+.3f}  median {np.median(d):+.3f}  abs_max {abs(d).max():.2f}  n0_diff {int(np.sum(d!=0))}/{len(d)}")


if __name__ == "__main__":
    main()
