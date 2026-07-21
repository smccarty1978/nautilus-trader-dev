"""Joint BE-arm × cat-SL sweep at 1s precision per gap group.

Population: RTH breakout-filter trades (bullish-bar, open-outside-zone)
on NQ.v.0 (continuous volume contract, no roll issue).

TIMESTAMP DISCIPLINE
--------------------
- 1s bars: ts_event = OPEN time → after load, ts_close = ts_event + 1s
- 1m bars: from resample(label='right', closed='right') → index IS ts_close
- Entry: 1s bar with ts_close = trigger_1m_ts_close + 1s (first 1s bar
  AFTER the 1m bar's close moment). This is finer than next-1m-open.

POLICY (per cell)
-----------------
- BE_arm_pts: when MFE first reaches this at 1s precision, schedule BE
  stop on the next 1s bar (BE_STOP_DELAY_BARS=1, NT-realistic).
- BE stop price: entry + 1 tick (long) / entry - 1 tick (short) — covers
  commission so rescued trades net ~$0.
- Pre-arm protective stop: min(cat_SL price, prior-level SL price)
  - cat_SL = entry ± cat_SL_pts (or "no-cat" → prior-level SL only)
- Post-arm: cat_SL REMOVED. BE-stop becomes the only protective stop.
- PT = next-level - 2.5 (always active)
- EOD: flat at 16:00 CT bar (existing precompute_eod_1s)
- Within-bar exit priority: cat/SL > BE > PT (conservative)

CHAIN (skip-while-open)
-----------------------
Built on the no-BE/no-cat baseline (prior-level SL only) so the trade
population is identical across all cells (apples-to-apples comparison).
Per-trade simulation is independent.

GRID PER GROUP
--------------
A_25pt    PT~22.5: BE [5, 7.5, 10, 12.5, 15] × cat_SL [8, 12, 16, 20, no-cat]
B_14_15pt PT~13:   BE [3, 4, 5, 6, 8]         × cat_SL [6, 8, 10, 12, no-cat]
C_10_11pt PT~9:    BE [2, 3, 4, 5, 6]         × cat_SL [5, 7, 9, 11, no-cat]
"""
from __future__ import annotations

import os, sys, time
from pathlib import Path
import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))
os.chdir(project_root)

from studies.level_momentum_continuation.level_study import (
    load_v0_1s, resample_1s_to_1m, annotate_sessions_ct,
)
from studies.level_momentum_continuation.analyze_breakout_filter import (
    detect_triggers_breakout, assign_group,
)
from studies.level_momentum_continuation.analyze_1s_precision import (
    annotate_sessions_1s, precompute_eod_1s, map_1m_trigger_to_1s_entry,
)

OUT = Path("studies/level_momentum_continuation/results_breakout")
OUT.mkdir(parents=True, exist_ok=True)

NQ_DOLLAR_PER_PT = 20.0
COMMISSION_PTS = 0.25
TICK_SIZE = 0.25
BE_STOP_DELAY_BARS = 1
BE_STOP_OFFSET_TICKS = 1
NO_CAT_SENTINEL = 9999.0   # effectively no cat-SL

# Per-group sweep grids
GRIDS = {
    "A_25pt":    {"be":  [5.0, 7.5, 10.0, 12.5, 15.0],
                  "cat": [8.0, 12.0, 16.0, 20.0, NO_CAT_SENTINEL]},
    "B_14_15pt": {"be":  [3.0, 4.0, 5.0, 6.0, 8.0],
                  "cat": [6.0, 8.0, 10.0, 12.0, NO_CAT_SENTINEL]},
    "C_10_11pt": {"be":  [2.0, 3.0, 4.0, 5.0, 6.0],
                  "cat": [5.0, 7.0, 9.0, 11.0, NO_CAT_SENTINEL]},
}


# ---------------- Per-trade simulation (vectorized) ----------------

def simulate_trade_policy(
    entry_1s_idx: int, di: int,
    entry_px: float, target: float, prior_sl_px: float,
    eod_idx: int,
    highs_1s: np.ndarray, lows_1s: np.ndarray, closes_1s: np.ndarray,
    be_arm_pts: float, cat_sl_pts: float,
):
    """Simulate one trade under (be_arm_pts, cat_sl_pts) policy.
    Returns dict with outcome, exit_idx_global, pnl_gross, pnl_net.

    Pre-arm protective stop: tighter of cat_SL and prior-level SL.
    Post-arm: BE-stop only (cat_SL & prior_SL removed).
    """
    n = len(highs_1s)
    last = min(eod_idx, n - 1)
    if entry_1s_idx >= n or last < entry_1s_idx:
        return None

    sli_h = highs_1s[entry_1s_idx : last + 1]
    sli_l = lows_1s[entry_1s_idx : last + 1]
    sli_c = closes_1s[entry_1s_idx : last + 1]
    nbars = len(sli_h)

    # Build pre-arm protective stop = tighter of cat_SL and prior_SL
    if di == 1:
        cat_px = entry_px - cat_sl_pts
        protect_px_pre = max(cat_px, prior_sl_px)
        be_px = entry_px + BE_STOP_OFFSET_TICKS * TICK_SIZE
        # MFE for arming
        running_mfe = np.maximum.accumulate(sli_h - entry_px)
        be_arm_mask = running_mfe >= be_arm_pts
        be_armed_at = (int(np.argmax(be_arm_mask))
                       if be_arm_mask.any() else -1)
        # Pre-arm protective hit (low <= protect_px_pre)
        pre_hit = sli_l <= protect_px_pre
        pre_idx = int(np.argmax(pre_hit)) if pre_hit.any() else -1
        # Target hit
        tgt_hit = sli_h >= target
        tgt_idx = int(np.argmax(tgt_hit)) if tgt_hit.any() else -1
        # BE-stop hit (low <= be_px) AFTER arming + delay
        if be_armed_at >= 0:
            start = be_armed_at + BE_STOP_DELAY_BARS
            if start < nbars:
                be_hit = sli_l[start:] <= be_px
                be_idx = (start + int(np.argmax(be_hit))
                          if be_hit.any() else -1)
            else:
                be_idx = -1
        else:
            be_idx = -1
    else:
        cat_px = entry_px + cat_sl_pts
        protect_px_pre = min(cat_px, prior_sl_px)
        be_px = entry_px - BE_STOP_OFFSET_TICKS * TICK_SIZE
        running_mfe = np.maximum.accumulate(entry_px - sli_l)
        be_arm_mask = running_mfe >= be_arm_pts
        be_armed_at = (int(np.argmax(be_arm_mask))
                       if be_arm_mask.any() else -1)
        pre_hit = sli_h >= protect_px_pre
        pre_idx = int(np.argmax(pre_hit)) if pre_hit.any() else -1
        tgt_hit = sli_l <= target
        tgt_idx = int(np.argmax(tgt_hit)) if tgt_hit.any() else -1
        if be_armed_at >= 0:
            start = be_armed_at + BE_STOP_DELAY_BARS
            if start < nbars:
                be_hit = sli_h[start:] >= be_px
                be_idx = (start + int(np.argmax(be_hit))
                          if be_hit.any() else -1)
            else:
                be_idx = -1
        else:
            be_idx = -1

    # Build candidate exits
    candidates = []
    if pre_idx >= 0:
        # Pre-arm protective fires only if it precedes arming
        if be_armed_at == -1 or pre_idx < be_armed_at:
            candidates.append((pre_idx, "pre_arm_loss", protect_px_pre))
    if be_idx >= 0:
        candidates.append((be_idx, "be_stop", be_px))
    if tgt_idx >= 0:
        candidates.append((tgt_idx, "win", target))

    if not candidates:
        outcome = "eod_flat"
        exit_idx_in_slice = nbars - 1
        exit_px = float(sli_c[-1])
    else:
        # Earliest wins; ties broken by candidate priority
        # (pre_arm_loss > be_stop > win = conservative)
        candidates.sort(key=lambda x: (x[0],
            0 if x[1] == "pre_arm_loss" else
            (1 if x[1] == "be_stop" else 2)))
        exit_idx_in_slice, outcome, exit_px = candidates[0]

    pnl_gross = (exit_px - entry_px) * di
    return {
        "outcome": outcome,
        "exit_idx_global": entry_1s_idx + exit_idx_in_slice,
        "exit_px": float(exit_px),
        "pnl_gross": float(pnl_gross),
        "pnl_net": float(pnl_gross - COMMISSION_PTS),
        "be_armed": be_armed_at >= 0,
    }


# ---------------- Trade harvest (build fixed chain on baseline) ----------------

def harvest_trades_baseline(year: int):
    """For one year: load 1s+1m, detect triggers, build chain on
    no-BE/no-cat baseline. Returns list of trade dicts and the 1s
    arrays needed for replay.

    Baseline policy: BE_arm = inf (never arm), cat_SL = inf
    (no cat) — so only prior-level SL is the active stop.
    """
    print(f"\n[{year}] loading 1s ({Path('data/raw') / f'NQ_v0_1s_{year}.parquet'})...")
    bars_1s = load_v0_1s(Path(f"data/raw/NQ_v0_1s_{year}.parquet"))
    bars_1s = annotate_sessions_1s(bars_1s)
    print(f"  1s bars: {len(bars_1s):,}")

    print(f"[{year}] resampling to 1m & detecting triggers...")
    bars_1m = bars_1s[
        ["open", "high", "low", "close", "volume"]
    ].resample("1min", label="right", closed="right").agg({
        "open": "first", "high": "max", "low": "min",
        "close": "last", "volume": "sum"
    }).dropna(subset=["open", "high", "low", "close"])
    bars_1m = annotate_sessions_ct(bars_1m)
    triggers = detect_triggers_breakout(bars_1m)
    print(f"  triggers: {len(triggers):,}")

    bars_1s_reset = bars_1s.reset_index(drop=False)
    opens = bars_1s_reset["open"].values.astype(np.float64)
    highs = bars_1s_reset["high"].values.astype(np.float64)
    lows = bars_1s_reset["low"].values.astype(np.float64)
    closes = bars_1s_reset["close"].values.astype(np.float64)
    sessions = bars_1s_reset["session"].values
    ts_close_1s = pd.DatetimeIndex(bars_1s_reset["ts_close"])
    if ts_close_1s.tz is None:
        ts_close_1s = ts_close_1s.tz_localize("UTC")
    else:
        ts_close_1s = ts_close_1s.tz_convert("UTC")
    next_eod = precompute_eod_1s(bars_1s_reset)

    # Build chain on baseline (no BE, no cat — only prior-level SL)
    print(f"[{year}] building skip-while-open chain on baseline...")
    trades = []
    last_chain_exit = -1
    for tr in triggers:
        ts = pd.Timestamp(tr["bar_ts_close"])
        if ts.tz is None:
            ts = ts.tz_localize("UTC")
        else:
            ts = ts.tz_convert("UTC")
        e = map_1m_trigger_to_1s_entry(ts, ts_close_1s)
        if e < 0:
            continue
        if e <= last_chain_exit:
            continue
        di = tr["direction"]
        entry_px = float(opens[e])
        eod = int(next_eod[e])
        # Baseline simulation
        r = simulate_trade_policy(
            e, di, entry_px, float(tr["target"]), float(tr["stop"]),
            eod, highs, lows, closes,
            be_arm_pts=1e9,        # never arm
            cat_sl_pts=NO_CAT_SENTINEL,
        )
        if r is None:
            continue
        # Filter to RTH at entry
        if sessions[e] != "RTH":
            last_chain_exit = r["exit_idx_global"]
            continue
        trades.append({
            "year": year,
            "trigger_ts": ts,
            "entry_1s_idx": e,
            "entry_px": entry_px,
            "direction": di,
            "target": float(tr["target"]),
            "prior_sl": float(tr["stop"]),
            "eod_idx": eod,
            "level_pair": tr["level_pair"],
            "group": assign_group(tr["level_pair"]),
            # Cache the slice array LENGTH/refs so we can replay
        })
        last_chain_exit = r["exit_idx_global"]

    print(f"  RTH trades on baseline chain: {len(trades):,}")
    return trades, highs, lows, closes


# ---------------- Per-cell sweep ----------------

def sweep_cell(trades: list, highs, lows, closes,
               be_arm_pts: float, cat_sl_pts: float):
    """Run all trades through (be_arm, cat_sl). Returns metrics dict."""
    n = len(trades)
    if n == 0:
        return {"n": 0}
    pnl = np.zeros(n)
    outcome = np.empty(n, dtype="<U16")
    armed = np.zeros(n, dtype=bool)
    for i, t in enumerate(trades):
        r = simulate_trade_policy(
            t["entry_1s_idx"], t["direction"], t["entry_px"],
            t["target"], t["prior_sl"], t["eod_idx"],
            highs, lows, closes, be_arm_pts, cat_sl_pts)
        if r is None:
            outcome[i] = "skip"
            continue
        pnl[i] = r["pnl_net"]
        outcome[i] = r["outcome"]
        armed[i] = r["be_armed"]
    valid = outcome != "skip"
    nv = int(valid.sum())
    if nv == 0:
        return {"n": 0}
    pnl_v = pnl[valid]
    out_v = outcome[valid]
    n_win = int((out_v == "win").sum())
    n_be = int((out_v == "be_stop").sum())
    n_pre = int((out_v == "pre_arm_loss").sum())
    n_eod = int((out_v == "eod_flat").sum())
    return {
        "n": nv,
        "wr": n_win / nv,
        "win_rate": n_win / nv,
        "be_rate": n_be / nv,
        "pre_loss_rate": n_pre / nv,
        "eod_rate": n_eod / nv,
        "armed_rate": float(armed[valid].mean()),
        "mean_pnl_pts": float(pnl_v.mean()),
        "mean_pnl_dollars": float(pnl_v.mean() * NQ_DOLLAR_PER_PT),
        "total_pnl_dollars": float(pnl_v.sum() * NQ_DOLLAR_PER_PT),
        "n_win": n_win, "n_be": n_be,
        "n_pre": n_pre, "n_eod": n_eod,
    }


# ---------------- Main ----------------

def main():
    t0 = time.time()
    all_trades = []
    cached_arrays = {}

    for year in (2024, 2025):
        trades, highs, lows, closes = harvest_trades_baseline(year)
        cached_arrays[year] = (highs, lows, closes)
        for t in trades:
            t["_year"] = year
            all_trades.append(t)

    print(f"\nTotal RTH trades across years: {len(all_trades):,}")

    # Group trades by year (need separate 1s arrays per year)
    print(f"\n{'='*78}")
    print("Per-cell sweep: BE × cat-SL grid per group")
    print(f"{'='*78}")

    summary_rows = []
    for grp_label, grid in GRIDS.items():
        be_grid = grid["be"]
        cat_grid = grid["cat"]
        # Trades in this group (across years)
        gt = [t for t in all_trades if t["group"] == grp_label]
        if len(gt) == 0:
            continue
        print(f"\n[{grp_label}] n_trades={len(gt):,}, "
              f"sweep {len(be_grid)}×{len(cat_grid)} cells")

        # Build per-cell results, processing per-year so we use correct
        # 1s arrays
        by_year = {y: [t for t in gt if t["_year"] == y]
                   for y in (2024, 2025)}

        cell_table = []
        for be in be_grid:
            for cat in cat_grid:
                # Aggregate across years
                pnls = []
                outcomes = []
                armed_flags = []
                for y in (2024, 2025):
                    h, l, c = cached_arrays[y]
                    yt = by_year[y]
                    if not yt:
                        continue
                    for t in yt:
                        r = simulate_trade_policy(
                            t["entry_1s_idx"], t["direction"],
                            t["entry_px"], t["target"], t["prior_sl"],
                            t["eod_idx"], h, l, c, be, cat)
                        if r is None:
                            continue
                        pnls.append(r["pnl_net"])
                        outcomes.append(r["outcome"])
                        armed_flags.append(r["be_armed"])
                pnls = np.array(pnls)
                outcomes = np.array(outcomes)
                armed_flags = np.array(armed_flags)
                if len(pnls) == 0:
                    continue
                n = len(pnls)
                n_win = int((outcomes == "win").sum())
                n_be = int((outcomes == "be_stop").sum())
                n_pre = int((outcomes == "pre_arm_loss").sum())
                n_eod = int((outcomes == "eod_flat").sum())
                cat_label = ("no-cat" if cat >= NO_CAT_SENTINEL
                             else f"{cat:g}")
                row = {
                    "group": grp_label, "be_arm": be, "cat_sl": cat_label,
                    "n": n,
                    "wr": n_win / n, "be_rate": n_be / n,
                    "pre_loss_rate": n_pre / n, "eod_rate": n_eod / n,
                    "armed_rate": float(armed_flags.mean()),
                    "mean_pnl_pts": float(pnls.mean()),
                    "mean_pnl_dollars": float(pnls.mean() * NQ_DOLLAR_PER_PT),
                    "total_pnl_dollars": float(pnls.sum() * NQ_DOLLAR_PER_PT),
                }
                cell_table.append(row)
        df = pd.DataFrame(cell_table)
        df.to_csv(OUT / f"be_cat_sweep_{grp_label}.csv", index=False)
        summary_rows.append((grp_label, df))

        # Print mean $/trade heatmap (BE rows × cat cols)
        print(f"\n[{grp_label}] mean $/trade   (rows=BE_arm pts, "
              f"cols=cat_SL pts)")
        pivot = df.pivot(index="be_arm", columns="cat_sl",
                         values="mean_pnl_dollars")
        # Order columns numerically with no-cat last
        cat_cols = sorted(
            [c for c in pivot.columns if c != "no-cat"],
            key=lambda x: float(x))
        if "no-cat" in pivot.columns:
            cat_cols.append("no-cat")
        pivot = pivot[cat_cols]
        print(pivot.round(2).to_string())

        print(f"\n[{grp_label}] total $    (rows=BE_arm, cols=cat_SL)")
        pivot_t = df.pivot(index="be_arm", columns="cat_sl",
                           values="total_pnl_dollars")
        pivot_t = pivot_t[cat_cols]
        print(pivot_t.round(0).to_string())

        # Top 3 cells by mean $/tr
        print(f"\n[{grp_label}] top 3 cells by mean $/trade:")
        top = df.nlargest(3, "mean_pnl_dollars")
        for _, r in top.iterrows():
            print(f"  BE={r['be_arm']:>5.1f} cat={r['cat_sl']:>6} "
                  f"| n={int(r['n']):>5,} "
                  f"WR={100*r['wr']:>4.1f}% "
                  f"BE-rate={100*r['be_rate']:>4.1f}% "
                  f"pre-loss={100*r['pre_loss_rate']:>4.1f}% "
                  f"armed={100*r['armed_rate']:>4.1f}% "
                  f"| ${r['mean_pnl_dollars']:>+7.2f}/tr "
                  f"total ${r['total_pnl_dollars']:>+10,.0f}")

    # Combined summary
    if summary_rows:
        all_df = pd.concat([d for _, d in summary_rows],
                            ignore_index=True)
        all_df.to_csv(OUT / "be_cat_sweep_all.csv", index=False)
        print(f"\nSaved: {OUT / 'be_cat_sweep_all.csv'}")

    print(f"\n[done] runtime: {time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()
