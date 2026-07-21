"""Exit retest with corrected sim (no look-ahead).

Walks 1s bars from entry_ts + 60s (bar+1 close) to exit_ts + 60s
(flip bar close). Tests 5 exit strategy groups on 2025 confirmed
flip trades.
"""

import sys
import os
from pathlib import Path

project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))
os.chdir(project_root)

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import time as _time
import pandas as pd
import numpy as np
from numba import njit

from nautilus_trader.persistence.catalog import ParquetDataCatalog

NQ_MULT = 20.0
COMMISSION = 5.0
OUT_FILE = "studies/1m_confirmed_flip/results/exit_retest_v3.parquet"


@njit(cache=True)
def walk_trade(
    entry_px, direction, atr, regime_close_px,
    h_arr, l_arr, c_arr, ts_arr,
    pt_atr, sl_atr,
    trail_dist_atr, trail_activ_atr,
    be_activ_atr, time_limit_s,
):
    """Unified walker. -1 means feature disabled."""
    n = len(h_arr)
    if n == 0 or atr <= 0:
        return regime_close_px, 4, 0.0, 0  # 4 = regime_end

    peak_px = entry_px
    trail_active = False
    be_activated = False
    sl_px_curr = entry_px - direction * sl_atr * atr if sl_atr > 0 else 0.0
    pt_px = entry_px + direction * pt_atr * atr if pt_atr > 0 else 0.0
    time_exit_ts = (ts_arr[0] + int(time_limit_s * 1e9)
                    if time_limit_s > 0 else 0)

    for i in range(n):
        h = h_arr[i]
        l = l_arr[i]
        ts = ts_arr[i]

        # Time exit
        if time_limit_s > 0 and ts >= time_exit_ts:
            return c_arr[i], 3, abs(peak_px - entry_px) / atr, i  # 3=time

        # PT check (intra-bar)
        if pt_atr > 0:
            if direction == 1 and h >= pt_px:
                return pt_px, 0, abs(peak_px - entry_px) / atr, i  # 0=pt
            elif direction == -1 and l <= pt_px:
                return pt_px, 0, abs(peak_px - entry_px) / atr, i

        # SL check (intra-bar)
        if sl_atr > 0:
            if direction == 1 and l <= sl_px_curr:
                return sl_px_curr, 1, abs(peak_px - entry_px) / atr, i
            elif direction == -1 and h >= sl_px_curr:
                return sl_px_curr, 1, abs(peak_px - entry_px) / atr, i  # 1=sl

        # Update peak (must be AFTER PT/SL check since they fire intra-bar)
        if direction == 1:
            if h > peak_px:
                peak_px = h
        else:
            if l < peak_px:
                peak_px = l

        # Trail logic
        if trail_dist_atr > 0:
            mfe = (peak_px - entry_px) / atr if direction == 1 \
                else (entry_px - peak_px) / atr
            if not trail_active and mfe >= trail_activ_atr:
                trail_active = True
            if trail_active:
                trail_stop = (peak_px - direction * trail_dist_atr * atr)
                if direction == 1 and l <= trail_stop:
                    return trail_stop, 2, mfe, i  # 2=trail
                elif direction == -1 and h >= trail_stop:
                    return trail_stop, 2, mfe, i

        # Breakeven adjustment
        if be_activ_atr > 0 and not be_activated:
            mfe = (peak_px - entry_px) / atr if direction == 1 \
                else (entry_px - peak_px) / atr
            if mfe >= be_activ_atr:
                be_activated = True
                sl_px_curr = entry_px  # Move SL to entry

    # No exit — regime fallback
    return regime_close_px, 4, abs(peak_px - entry_px) / atr, n


REASON_LABELS = ["pt_hit", "sl_hit", "trail_hit", "time_exit", "regime_end"]


def run_config(name, trades, h_arr_list, l_arr_list, c_arr_list, ts_arr_list,
               pt=-1, sl=-1, trail_dist=-1, trail_activ=-1,
               be_activ=-1, time_s=-1):
    """Run one exit config across all trades."""
    n = len(trades)
    pnl_d = np.empty(n)
    reasons = np.empty(n, dtype=np.int32)
    peak_mfes = np.empty(n)
    bars_held = np.empty(n, dtype=np.int64)

    entry_px = trades["entry_price"].values
    direction = trades["direction"].values.astype(np.int64)
    atr = trades["atr_at_flip"].values
    reg_close = trades["exit_price"].values  # collector regime_pnl exit price

    for k in range(n):
        h, r, pm, bh = walk_trade(
            entry_px[k], direction[k], atr[k], reg_close[k],
            h_arr_list[k], l_arr_list[k], c_arr_list[k], ts_arr_list[k],
            float(pt) if pt > 0 else -1.0,
            float(sl) if sl > 0 else -1.0,
            float(trail_dist) if trail_dist > 0 else -1.0,
            float(trail_activ) if trail_activ > 0 else 0.0,
            float(be_activ) if be_activ > 0 else -1.0,
            float(time_s) if time_s > 0 else -1.0,
        )
        # h is exit_price
        pnl_pts = (h - entry_px[k]) * direction[k]
        pnl_d[k] = pnl_pts * NQ_MULT - COMMISSION
        reasons[k] = r
        peak_mfes[k] = pm
        bars_held[k] = bh

    return {
        "name": name,
        "pt": pt, "sl": sl,
        "trail_dist": trail_dist, "trail_activ": trail_activ,
        "be_activ": be_activ, "time_s": time_s,
        "n": n,
        "pnl": pnl_d,
        "reasons": reasons,
        "peak_mfes": peak_mfes,
        "bars_held": bars_held,
    }


def summarize(res):
    """Compute summary stats from result dict."""
    pnl = res["pnl"]
    avg = pnl.mean()
    total = pnl.sum()
    wr = (pnl > 0).mean() * 100
    gw = pnl[pnl > 0].sum()
    gl = abs(pnl[pnl <= 0].sum())
    pf = gw / gl if gl > 0 else 999.0

    # Drawdown on cumulative PnL
    cum = pnl.cumsum()
    peak = np.maximum.accumulate(cum)
    dd = (peak - cum).max()

    # Exit reason % breakdown
    reasons = res["reasons"]
    reason_pcts = {lbl: (reasons == i).mean() * 100
                   for i, lbl in enumerate(REASON_LABELS)}
    return {
        "n": len(pnl), "avg": avg, "total": total, "wr": wr,
        "pf": pf, "dd": dd, **reason_pcts,
    }


def main():
    print("=" * 80)
    print("EXIT RETEST v3 — corrected sim (no look-ahead)")
    print("  Year: 2025 only")
    print("=" * 80)

    print("\nLoading trades (2025)...")
    trades = pd.read_parquet(
        "studies/1m_confirmed_flip/results/trades_all.parquet").copy()
    trades["entry_dt"] = pd.to_datetime(
        trades["entry_ts"], unit="ns", utc=True)
    trades = trades[
        (trades["entry_dt"] >= "2025-01-01") &
        (trades["entry_dt"] < "2026-01-01")
    ].reset_index(drop=True)
    print(f"  {len(trades):,} trades")

    print("\nLoading 1s bars (2025)...")
    t0 = _time.time()
    catalog = ParquetDataCatalog("data/catalog/NQ_2020_2025")
    bars_1s = catalog.bars(
        bar_types=["NQ.XCME-1-SECOND-LAST-EXTERNAL"],
        start=pd.Timestamp("2025-01-01", tz="UTC"),
        end=pd.Timestamp("2026-01-01", tz="UTC"))
    print(f"  {len(bars_1s):,} bars ({_time.time()-t0:.0f}s)")

    print("Extracting...")
    t0 = _time.time()
    n = len(bars_1s)
    ts_arr = np.empty(n, dtype=np.int64)
    high_arr = np.empty(n)
    low_arr = np.empty(n)
    close_arr = np.empty(n)
    for i, b in enumerate(bars_1s):
        ts_arr[i] = b.ts_event
        high_arr[i] = float(b.high)
        low_arr[i] = float(b.low)
        close_arr[i] = float(b.close)
    del bars_1s
    print(f"  Extracted ({_time.time()-t0:.0f}s)")

    # Pre-compute slices: from entry_ts + 60s to exit_ts + 60s
    print("\nPre-slicing trade windows...")
    t0 = _time.time()
    entry_walk = trades["entry_ts"].astype("int64").values + 60_000_000_000
    exit_walk = (pd.to_datetime(trades["exit_time"]).astype("int64").values
                 + 60_000_000_000)

    h_list = []
    l_list = []
    c_list = []
    ts_list = []
    skipped = 0
    for k in range(len(trades)):
        i_start = np.searchsorted(ts_arr, entry_walk[k], side="left")
        i_end = np.searchsorted(ts_arr, exit_walk[k], side="right")
        if i_end <= i_start:
            skipped += 1
        h_list.append(high_arr[i_start:i_end])
        l_list.append(low_arr[i_start:i_end])
        c_list.append(close_arr[i_start:i_end])
        ts_list.append(ts_arr[i_start:i_end])
    print(f"  Done ({_time.time()-t0:.0f}s)  empty windows: {skipped}")

    # ---- Build all configs ----
    configs = []

    # Group 1: Fixed brackets (PT/SL)
    for pt, sl in [(0.25, 0.25), (0.25, 0.50), (0.50, 0.25), (0.50, 0.50),
                    (0.50, 0.75), (0.75, 0.50), (0.75, 0.75),
                    (1.00, 0.50), (1.00, 0.75), (1.00, 1.00)]:
        configs.append({
            "group": "1_bracket",
            "name": f"PT{pt:.2f}_SL{sl:.2f}",
            "pt": pt, "sl": sl,
        })

    # Group 2: Trailing stops
    for td, ta in [(0.25, 0.25), (0.25, 0.50), (0.50, 0.50),
                    (0.50, 0.75), (0.75, 0.75), (1.00, 1.00)]:
        configs.append({
            "group": "2_trail",
            "name": f"Trail{td:.2f}_Act{ta:.2f}",
            "trail_dist": td, "trail_activ": ta,
        })

    # Group 3: PT + Trail hybrid (also has SL)
    for pt, td, ta, sl in [
        (1.00, 0.25, 0.25, 0.75),
        (1.00, 0.25, 0.50, 0.75),
        (0.75, 0.25, 0.25, 0.50),
        (0.75, 0.25, 0.50, 0.50),
        (0.50, 0.25, 0.25, 0.50),
        (1.50, 0.50, 0.75, 1.00),
    ]:
        configs.append({
            "group": "3_hybrid",
            "name": f"PT{pt:.2f}_TD{td:.2f}_TA{ta:.2f}_SL{sl:.2f}",
            "pt": pt, "trail_dist": td, "trail_activ": ta, "sl": sl,
        })

    # Group 4: Time-based
    for pt, sl, t_min in [(0.50, 0.50, 2), (0.50, 0.50, 5),
                           (0.75, 0.75, 5), (0.75, 0.75, 10),
                           (1.00, 1.00, 10)]:
        configs.append({
            "group": "4_time",
            "name": f"PT{pt:.2f}_SL{sl:.2f}_T{t_min}min",
            "pt": pt, "sl": sl, "time_s": t_min * 60,
        })

    # Group 5: Breakeven
    for pt, sl, be in [(0.50, 0.50, 0.25), (0.75, 0.75, 0.25),
                       (0.75, 0.75, 0.50), (1.00, 1.00, 0.50),
                       (1.00, 1.00, 0.75)]:
        configs.append({
            "group": "5_be",
            "name": f"PT{pt:.2f}_SL{sl:.2f}_BE{be:.2f}",
            "pt": pt, "sl": sl, "be_activ": be,
        })

    print(f"\nTesting {len(configs)} configs...\n")

    # JIT warmup
    print("  JIT warmup...", flush=True)
    t0 = _time.time()
    walk_trade(100.0, 1, 1.0, 100.0,
               np.array([100.0]), np.array([100.0]), np.array([100.0]),
               np.array([0], dtype=np.int64),
               1.0, 1.0, -1.0, 0.0, -1.0, -1.0)
    print(f"    Warmup done ({_time.time()-t0:.1f}s)")

    all_results = []
    summaries = []

    for idx, cfg in enumerate(configs):
        t0 = _time.time()
        kwargs = {k: v for k, v in cfg.items()
                  if k not in ("group", "name")}
        res = run_config(cfg["name"], trades,
                          h_list, l_list, c_list, ts_list, **kwargs)
        s = summarize(res)
        s["group"] = cfg["group"]
        s["name"] = cfg["name"]
        summaries.append(s)
        all_results.append(res)
        elapsed = _time.time() - t0
        print(f"  [{idx+1:>2}/{len(configs)}] {cfg['name']:<35} "
              f"avg=${s['avg']:>+7.1f} total=${s['total']:>+11,.0f} "
              f"WR={s['wr']:>5.1f}% PF={s['pf']:>5.2f} "
              f"({elapsed:.1f}s)")

    sdf = pd.DataFrame(summaries)
    sdf.to_parquet(OUT_FILE, index=False)

    # ---- Print rankings ----
    print(f"\n{'='*80}")
    print(f"BEST BY TOTAL PnL (top 10)")
    print(f"{'='*80}")
    print(f"{'Group':<12} {'Config':<32} {'N':>6} {'Avg$':>8} "
          f"{'Total$':>12} {'WR':>6} {'PF':>5} {'DD$':>9}")
    print("-" * 95)
    for _, r in sdf.nlargest(10, "total").iterrows():
        print(f"{r['group']:<12} {r['name']:<32} {r['n']:>6,} "
              f"${r['avg']:>+7.1f} ${r['total']:>+11,.0f} "
              f"{r['wr']:>5.1f}% {r['pf']:>5.2f} ${r['dd']:>8,.0f}")

    print(f"\n{'='*80}")
    print(f"BEST BY PROFIT FACTOR (top 10)")
    print(f"{'='*80}")
    print(f"{'Group':<12} {'Config':<32} {'N':>6} {'Avg$':>8} "
          f"{'Total$':>12} {'WR':>6} {'PF':>5} {'DD$':>9}")
    print("-" * 95)
    for _, r in sdf.nlargest(10, "pf").iterrows():
        print(f"{r['group']:<12} {r['name']:<32} {r['n']:>6,} "
              f"${r['avg']:>+7.1f} ${r['total']:>+11,.0f} "
              f"{r['wr']:>5.1f}% {r['pf']:>5.2f} ${r['dd']:>8,.0f}")

    # Exit reason % for top 5
    print(f"\n{'='*80}")
    print(f"EXIT REASON BREAKDOWN — top 5 by total")
    print(f"{'='*80}")
    print(f"{'Config':<35} {'PT%':>7} {'SL%':>7} {'Trail%':>7} "
          f"{'Time%':>7} {'Reg%':>7}")
    print("-" * 85)
    for _, r in sdf.nlargest(5, "total").iterrows():
        print(f"{r['name']:<35} {r['pt_hit']:>6.1f}% {r['sl_hit']:>6.1f}% "
              f"{r['trail_hit']:>6.1f}% {r['time_exit']:>6.1f}% "
              f"{r['regime_end']:>6.1f}%")

    # By group
    print(f"\n{'='*80}")
    print(f"BEST BY GROUP")
    print(f"{'='*80}")
    for g in sorted(sdf["group"].unique()):
        gdf = sdf[sdf["group"] == g]
        b = gdf.loc[gdf["total"].idxmax()]
        print(f"  {g}: {b['name']}  "
              f"avg=${b['avg']:+.1f}  total=${b['total']:+,.0f}  "
              f"PF={b['pf']:.2f}")

    print(f"\nSaved summary: {OUT_FILE}")
    print(f"\n{'='*80}")


if __name__ == "__main__":
    main()
