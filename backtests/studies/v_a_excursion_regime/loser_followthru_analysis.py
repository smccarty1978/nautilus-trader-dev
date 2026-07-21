"""Analyze the loser/no-flip cohort for missed follow-through.

For each of the 1,177 NT MBP-1 trades:
1. Find next 1m regime flip in our direction after entry_ts
2. Compute MFE/MAE evolution from 1s bars (sampled at 15s, 30s, 60s,
   120s, 300s, 600s, 1200s, 1800s)
3. Simulate hypothetical exit policies (longer hold, MFE-trigger)

Output:
- Eventual-flip distribution for no-flip cohort
- MFE grid per cohort (VA-confirm / no-flip / all)
- Hypothetical policy PnL (hold-to-T, exit-on-MFE-target)
"""
from __future__ import annotations
import os, sys, time
from pathlib import Path

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))
os.chdir(project_root)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import numpy as np
import pandas as pd


NT_MBP1_TRADES = ("backtests/pre_flip_T1/results/"
                    "nt_mbp1_2026_top10_N20/trades_all_months.parquet")
RAW_1S = "data/raw/NQ_v0_1s_2026_ytd.parquet"
SNAPSHOTS = ("collectors/collector_v2/results/v_a_v0_2026/"
               "snapshots_with_vol_vwap.parquet")
HORIZONS_S = [15, 30, 60, 120, 300, 600, 1200, 1800]
NQ_MULT = 20.0
COMMISSION_RT = 10.0   # $5 per side


def main():
    t0 = time.time()
    print("Loading inputs...")
    trades = pd.read_parquet(NT_MBP1_TRADES)
    trades = trades[trades["exit_filled"]].copy().reset_index(drop=True)
    trades["entry_ts_ns"] = trades["entry_ts_ns"].astype("int64")
    print(f"  {len(trades):,} trades")

    # Load all regime flips in 2026
    snap = pd.read_parquet(SNAPSHOTS,
                              columns=["kind", "decision_ts",
                                        "direction", "session",
                                        "atr_1m"])
    flips = snap[(snap["kind"] == "regime_flip")
                    & (snap["session"] == "RTH")].copy()
    flips["decision_ts"] = flips["decision_ts"].astype("int64")
    flips["flip_bar_close_ts"] = flips["decision_ts"] - 1_000_000_000
    flips = flips.sort_values("decision_ts").reset_index(drop=True)
    print(f"  {len(flips):,} RTH regime flips in 2026")

    # Per-direction flip arrays for fast bisect
    flips_up_ts = flips[flips["direction"] == 1
                          ]["flip_bar_close_ts"].to_numpy()
    flips_dn_ts = flips[flips["direction"] == -1
                          ]["flip_bar_close_ts"].to_numpy()

    # Load 1s bars for 2026 YTD into pandas (timestamp is the index)
    bars = pd.read_parquet(RAW_1S, columns=["open", "high", "low",
                                                "close"])
    bars.index = pd.to_datetime(bars.index, utc=True)
    bars = bars.sort_index()
    bars["ts"] = bars.index.view("int64")
    # ts is OPEN time of 1s bar; for high/low touch detection within
    # [entry, entry+T] we want bars whose OPEN >= entry_ts AND OPEN <
    # entry_ts + T. searchsorted does this correctly.
    bars = bars.reset_index(drop=True)
    print(f"  {len(bars):,} 1s bars  ({time.time()-t0:.0f}s)")
    print(f"  bar cols: {list(bars.columns)[:8]}")

    ts_arr = bars["ts"].to_numpy()
    high_arr = bars["high"].to_numpy().astype("float64")
    low_arr = bars["low"].to_numpy().astype("float64")
    close_arr = bars["close"].to_numpy().astype("float64")

    # Per-trade: compute MFE/MAE at each horizon + time-to-flip
    rows = []
    for i, tr in trades.iterrows():
        entry_ts = int(tr["entry_ts_ns"])
        d = int(tr["direction"])
        entry_px = float(tr["entry_fill_price"])
        atr = float(tr.get("atr_at_signal", np.nan))
        idx0 = np.searchsorted(ts_arr, entry_ts, side="left")

        # Time to next regime flip in our direction
        if d == 1:
            f = flips_up_ts[
                np.searchsorted(flips_up_ts, entry_ts, side="right"):]
        else:
            f = flips_dn_ts[
                np.searchsorted(flips_dn_ts, entry_ts, side="right"):]
        next_flip_ts = int(f[0]) if len(f) else 0
        time_to_flip_s = (
            (next_flip_ts - entry_ts) / 1e9
            if next_flip_ts > 0 else np.nan)

        # MFE/MAE at each horizon (in points and ATR)
        h_mfe = {}
        h_mae = {}
        h_close_pnl = {}
        for h in HORIZONS_S:
            end_ts = entry_ts + h * 1_000_000_000
            idx1 = np.searchsorted(ts_arr, end_ts, side="right")
            if idx1 <= idx0:
                idx1 = idx0 + 1
            if idx1 > len(ts_arr):
                idx1 = len(ts_arr)
            h_seg = high_arr[idx0:idx1]
            l_seg = low_arr[idx0:idx1]
            c_seg = close_arr[idx0:idx1]
            if len(h_seg) == 0:
                continue
            if d == 1:
                mfe_pts = max(h_seg.max() - entry_px, 0.0)
                mae_pts = max(entry_px - l_seg.min(), 0.0)
                close_pnl = (c_seg[-1] - entry_px)
            else:
                mfe_pts = max(entry_px - l_seg.min(), 0.0)
                mae_pts = max(h_seg.max() - entry_px, 0.0)
                close_pnl = (entry_px - c_seg[-1])
            h_mfe[h] = mfe_pts
            h_mae[h] = mae_pts
            h_close_pnl[h] = close_pnl

        row = {
            "i": i,
            "entry_ts_ns": entry_ts,
            "direction": d,
            "entry_fill_price": entry_px,
            "atr_at_signal": atr,
            "is_va_confirm": bool(tr["is_va_confirm"]),
            "actual_net_pnl": float(tr["net_pnl"]),
            "actual_pnl_pts": float(tr["pnl_pts"]),
            "next_flip_ts": next_flip_ts,
            "time_to_flip_s": time_to_flip_s,
        }
        for h in HORIZONS_S:
            row[f"mfe_pts_{h}s"] = h_mfe.get(h, np.nan)
            row[f"mae_pts_{h}s"] = h_mae.get(h, np.nan)
            row[f"close_pnl_pts_{h}s"] = h_close_pnl.get(h, np.nan)
            if not np.isnan(atr) and atr > 0:
                row[f"mfe_atr_{h}s"] = h_mfe.get(h, np.nan) / atr
                row[f"mae_atr_{h}s"] = h_mae.get(h, np.nan) / atr
        rows.append(row)
    res = pd.DataFrame(rows)
    print(f"\n  Computed {len(res):,} trade MFE grids  "
          f"({time.time()-t0:.0f}s)")

    # ===== Filter contract-roll / data-artifact trades =====
    # Detection: bar close at the ACTUAL exit_ts should ~ match
    # exit_fill_price (within ~1 tick spread). If they diverge,
    # 1s OHLC contract series doesn't align with MBP-1 series.
    trades_meta = trades[["entry_ts_ns", "exit_ts_ns",
                              "exit_fill_price"]].copy()
    trades_meta["entry_ts_ns"] = trades_meta["entry_ts_ns"].astype(
        "int64")
    trades_meta["exit_ts_ns"] = trades_meta["exit_ts_ns"].astype(
        "int64")
    res = res.merge(trades_meta, on="entry_ts_ns", how="left")
    exit_idx = np.searchsorted(ts_arr, res["exit_ts_ns"].values,
                                  side="left")
    exit_idx = np.clip(exit_idx, 0, len(ts_arr) - 1)
    res["bar_close_at_exit_ts"] = close_arr[exit_idx]
    res["bar_vs_actual_exit_pts"] = (
        res["bar_close_at_exit_ts"] - res["exit_fill_price"]).abs()

    n_total = len(res)
    artifact_mask = res["bar_vs_actual_exit_pts"] > 5.0
    n_drop = int(artifact_mask.sum())
    print(f"\n  Data-artifact filter: dropping {n_drop} trades where "
          f"|bar_close_at_exit_ts - actual_exit_fill| > 5 pts")
    if n_drop:
        drop_examples = res[artifact_mask].head(8)
        for _, ex in drop_examples.iterrows():
            ts = pd.Timestamp(int(ex["entry_ts_ns"]), unit="ns",
                                  tz="UTC")
            print(f"    {ts}  d={int(ex['direction']):+d}  "
                  f"VA={ex['is_va_confirm']}  "
                  f"diff={float(ex['bar_vs_actual_exit_pts']):+.2f} pts")
    res_clean = res[~artifact_mask].copy().reset_index(drop=True)
    print(f"  Clean cohort: {len(res_clean):,} "
          f"(was {n_total:,})  "
          f"VA-confirm={int(res_clean['is_va_confirm'].sum())}")
    # Use clean cohort going forward
    res = res_clean

    res.to_parquet(
        "studies/v_a_excursion_regime/results_v0/"
        "loser_followthru_grid.parquet", index=False)

    # ===== Eventual-flip distribution =====
    print("\n" + "=" * 78)
    print("EVENTUAL REGIME FLIP DISTRIBUTION (no-flip cohort)")
    print("=" * 78)
    no_flip = res[~res["is_va_confirm"]].copy()
    print(f"No-flip cohort: n={len(no_flip):,}")
    flip_buckets = [
        ("≤ 60s   (= VA but timing miss?)", 0, 60),
        ("60-120s", 60, 120),
        ("120-300s (2-5 min)", 120, 300),
        ("300-600s (5-10 min)", 300, 600),
        ("600-1200s (10-20 min)", 600, 1200),
        ("1200-1800s (20-30 min)", 1200, 1800),
        ("1800s+  (eventually)", 1800, 10**9),
        ("never (no flip in 2026)", None, None),
    ]
    for name, lo, hi in flip_buckets:
        if lo is None:
            mask = no_flip["time_to_flip_s"].isna()
        else:
            mask = ((no_flip["time_to_flip_s"] > lo)
                      & (no_flip["time_to_flip_s"] <= hi))
        n = int(mask.sum())
        pct = n / len(no_flip) * 100
        print(f"  {name:<35} n={n:>4}  ({pct:>5.1f}%)")

    # Cumulative
    print("\nCumulative — % that eventually flip within...")
    for cutoff in [60, 120, 300, 600, 1200, 1800, 3600]:
        n = int((no_flip["time_to_flip_s"] <= cutoff).sum())
        pct = n / len(no_flip) * 100
        print(f"  {cutoff:>5}s: {n:>4} ({pct:>5.1f}%)")

    # ===== MFE grid per cohort =====
    print("\n" + "=" * 78)
    print("MFE DISTRIBUTION BY HORIZON (ATR units)")
    print("=" * 78)
    cohorts = [
        ("ALL", res),
        ("VA-confirm", res[res["is_va_confirm"]]),
        ("No-flip", res[~res["is_va_confirm"]]),
    ]
    for cname, csub in cohorts:
        print(f"\n  [{cname}] n={len(csub):,}")
        print(f"  {'horizon':<10} {'mean':>7} {'median':>8} {'p75':>7} "
              f"{'p90':>7} {'≥0.5atr':>9} {'≥1.0atr':>9} {'≥1.5atr':>9}")
        for h in HORIZONS_S:
            col = f"mfe_atr_{h}s"
            v = csub[col].dropna()
            if len(v) == 0:
                continue
            p50, p75, p90 = v.quantile([0.5, 0.75, 0.9]).tolist()
            ge05 = (v >= 0.5).mean()
            ge10 = (v >= 1.0).mean()
            ge15 = (v >= 1.5).mean()
            print(f"  {h:>5}s    {v.mean():>7.3f} {p50:>8.3f} "
                  f"{p75:>7.3f} {p90:>7.3f} "
                  f"{ge05:>8.1%} {ge10:>8.1%} {ge15:>8.1%}")

    # ===== Hypothetical exit policy: hold to T-seconds =====
    print("\n" + "=" * 78)
    print("HYPOTHETICAL POLICY 1: replace current exit with hold-to-T")
    print("=" * 78)
    print(f"  Policy: enter same trades, exit at entry_ts + T, "
          f"price = bar close at T")
    print(f"  Baseline (current 60s hold-or-flip): "
          f"${res['actual_net_pnl'].sum():+,.0f} "
          f"(${res['actual_net_pnl'].mean():+.2f}/tr)")
    print()
    print(f"  {'T':<8} {'total':>10} {'$/tr':>9} {'WR':>7} "
          f"{'mean_pts':>10}")
    for h in HORIZONS_S:
        col = f"close_pnl_pts_{h}s"
        v = res[col].dropna()
        if len(v) == 0:
            continue
        gross = v * NQ_MULT
        net = gross - COMMISSION_RT
        wr = (net > 0).mean()
        print(f"  {h:>5}s    ${net.sum():>+9,.0f} "
              f"${net.mean():>+7.2f} {wr:>6.1%} "
              f"{v.mean():>+9.3f}")

    # Per-cohort hold-to-T
    for cname, csub in [
        ("VA-confirm", res[res["is_va_confirm"]]),
        ("No-flip", res[~res["is_va_confirm"]])]:
        print(f"\n  [{cname}] n={len(csub):,}")
        print(f"  Baseline actual: "
              f"${csub['actual_net_pnl'].sum():+,.0f} "
              f"(${csub['actual_net_pnl'].mean():+.2f}/tr)")
        for h in HORIZONS_S:
            col = f"close_pnl_pts_{h}s"
            v = csub[col].dropna()
            if len(v) == 0:
                continue
            gross = v * NQ_MULT
            net = gross - COMMISSION_RT
            wr = (net > 0).mean()
            print(f"    {h:>5}s    ${net.sum():>+9,.0f} "
                  f"${net.mean():>+7.2f} WR={wr:>5.1%}")

    # ===== Hypothetical policy 2: take-profit at MFE target =====
    print("\n" + "=" * 78)
    print("HYPOTHETICAL POLICY 2: take-profit at MFE target (1800s max)")
    print("=" * 78)
    print(f"  Policy: if MFE ≥ X*ATR within 1800s, exit at X*ATR")
    print(f"          else exit at 1800s close")
    print()
    print(f"  {'TP':<8} {'total':>10} {'$/tr':>9} {'WR':>7} "
          f"{'hit_rate':>10}")
    for tp_atr in [0.5, 0.75, 1.0, 1.25, 1.5, 2.0]:
        pnl_pts = []
        for _, row in res.iterrows():
            atr = row["atr_at_signal"]
            if np.isnan(atr) or atr <= 0:
                pnl_pts.append(np.nan)
                continue
            target_pts = tp_atr * atr
            # find first horizon where MFE ≥ target
            hit = False
            for h in HORIZONS_S:
                if row[f"mfe_pts_{h}s"] >= target_pts:
                    pnl_pts.append(target_pts)
                    hit = True
                    break
            if not hit:
                pnl_pts.append(row[f"close_pnl_pts_1800s"])
        pnl_arr = np.array(pnl_pts, dtype="float64")
        gross = pnl_arr * NQ_MULT
        net = gross - COMMISSION_RT
        net = net[~np.isnan(net)]
        hit_rate = (~np.isnan(pnl_arr)
                       ).sum() / len(pnl_arr)
        # Compute hit_rate properly: hit means MFE ≥ target
        target_hits = []
        for _, row in res.iterrows():
            atr = row["atr_at_signal"]
            if np.isnan(atr) or atr <= 0:
                continue
            target_hits.append(
                row[f"mfe_pts_1800s"] >= tp_atr * atr)
        hit_rate = np.mean(target_hits) if target_hits else 0
        print(f"  {tp_atr:.2f}atr "
              f"${net.sum():>+9,.0f} ${net.mean():>+7.2f} "
              f"{(net > 0).mean():>6.1%} {hit_rate:>9.1%}")

    print(f"\n[done] runtime: {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
