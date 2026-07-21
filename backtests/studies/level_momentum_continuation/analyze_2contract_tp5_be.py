"""2-contract TP+5 / BE-on-C2 / cat_SL sweep at 1s precision.

POLICY
------
Two contracts entered at the open of the 1s bar following the 1m
trigger close.

  C1: limit TP at entry +/- 5 pts. Cat_SL also active on C1.
  C2: cat_SL pre-arm; BE+1tick post-arm. Original PT (next-level - 2.5)
      always active. After C1 TP fires at second T, BE+1tick replaces
      cat_SL on C2 starting at second T+1 (BE_DELAY=1s, NT-realistic).

Within-bar priority (conservative):
  cat_SL  >  C1_TP  >  C2_BE_stop  >  C2_PT

If both cat_SL and C1_TP are touched in the same 1s bar pre-arm, cat_SL
fires first (loss on both contracts). After cat_SL hits, C2 cannot arm.

CAT_SL GRID (per group)
-----------------------
  A_25pt:    [8, 10, 12, 15, 18, 20, no-cat]
  B_14_15pt: [6, 8, 10, 12, 14, no-cat]
  C_10_11pt: [4, 6, 8, 10, 12, no-cat]

Population: NQ.v.0 RTH 2024+2025, breakout-filter trades (bullish-bar /
open-outside-zone). Chain on no-policy baseline (prior-level SL only).

Bucket assignment uses 1s precision:
  win_clean         : outcome=win, MAE-before-first-MFE-2.5 < 2.0 pts
  win_vshape        : outcome=win, MAE-before-first-MFE-2.5 >= 2.0 pts
  loss_runthenbreak : outcome=loss, max MFE >= 2.5 pts
  loss_quick        : outcome=loss, max MFE < 2.5 pts

For the bucket assignment, "outcome" is the outcome of the BASELINE
(no-policy) sim — so buckets are fixed across cells.
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
COMMISSION_PTS = 0.25       # per contract round trip
TICK_SIZE = 0.25
TP_PTS = 5.0                # C1 partial profit target
BE_OFFSET = 1 * TICK_SIZE   # +1 tick BE
BE_DELAY = 1                # 1s delay after C1 TP before BE active
NO_CAT_SENTINEL = 9999.0

ARM_THRESHOLD = 2.5         # for loss bucket assignment
CLEAN_MAE_CAP = 3.0         # MAX MAE over full trade < this = clean
                            # (NEW DEFINITION as of May 2026 — was
                            # 2.0 with MAE-before-arm logic)

CAT_GRIDS = {
    "A_25pt":    [8.0, 10.0, 12.0, 15.0, 18.0, 20.0, NO_CAT_SENTINEL],
    "B_14_15pt": [6.0, 8.0, 10.0, 12.0, 14.0, NO_CAT_SENTINEL],
    "C_10_11pt": [4.0, 6.0, 8.0, 10.0, 12.0, NO_CAT_SENTINEL],
}


# ---------------- Baseline path simulation (for bucket assignment) ----------------

def sim_baseline_path(entry_idx, di, entry_px, target, prior_sl, eod_idx,
                      highs, lows, closes):
    """Walk path under no-policy (prior-level SL only). Returns
    outcome + MFE/MAE arrays for bucket assignment."""
    n = len(highs)
    last = min(eod_idx, n - 1)
    if entry_idx >= n or last < entry_idx:
        return None
    sli_h = highs[entry_idx : last + 1]
    sli_l = lows[entry_idx : last + 1]
    sli_c = closes[entry_idx : last + 1]
    nbars = len(sli_h)

    if di == 1:
        running_mfe = np.maximum.accumulate(sli_h - entry_px)
        running_mae = np.maximum.accumulate(entry_px - sli_l)
        sl_hit = sli_l <= prior_sl
        tgt_hit = sli_h >= target
    else:
        running_mfe = np.maximum.accumulate(entry_px - sli_l)
        running_mae = np.maximum.accumulate(sli_h - entry_px)
        sl_hit = sli_h >= prior_sl
        tgt_hit = sli_l <= target

    sl_idx = int(np.argmax(sl_hit)) if sl_hit.any() else nbars
    tgt_idx = int(np.argmax(tgt_hit)) if tgt_hit.any() else nbars
    if sl_idx == nbars and tgt_idx == nbars:
        outcome = "eod_flat"; exit_idx = nbars - 1
    elif sl_idx <= tgt_idx:
        outcome = "loss"; exit_idx = sl_idx
    else:
        outcome = "win"; exit_idx = tgt_idx

    return {
        "outcome": outcome,
        "exit_idx_global": entry_idx + exit_idx,
        "mfe_t": running_mfe[: exit_idx + 1],
        "mae_t": running_mae[: exit_idx + 1],
        "max_mfe": float(running_mfe[exit_idx]),
        "max_mae": float(running_mae[exit_idx]),
    }


def assign_bucket(outcome, mfe_t, mae_t, max_mfe):
    """Bucket assignment (NEW DEFINITION as of May 2026):
      win_clean         = win AND max_mae over FULL trade < CLEAN_MAE_CAP (3 pts)
      win_vshape        = win AND max_mae over full trade >= 3 pts
      loss_runthenbreak = loss AND max_mfe >= ARM_THRESHOLD (2.5 pts)
      loss_quick        = loss AND max_mfe < ARM_THRESHOLD
      timed_out         = anything else (eod_flat etc.)

    OLD (deprecated): clean was MAE-BEFORE-FIRST-+2.5-MFE < 2 pts.
    Old definition let trades count as 'clean' even when they had
    large LATE MAE (post-arm), which broke SL design intuition.
    """
    if outcome == "win":
        max_mae_full = float(mae_t.max()) if len(mae_t) > 0 else 0.0
        return ("win_clean" if max_mae_full < CLEAN_MAE_CAP
                else "win_vshape")
    elif outcome == "loss":
        return ("loss_runthenbreak" if max_mfe >= ARM_THRESHOLD
                else "loss_quick")
    else:
        return "timed_out"


# ---------------- 2-contract policy simulation ----------------

def sim_2contract(entry_idx, di, entry_px, pt_px, prior_sl_px, eod_idx,
                  cat_sl_pts, highs, lows, closes):
    """Simulate 2-contract policy with C1 TP=+5 and C2 BE-on-arm.

    Returns dict with C1 outcome + price + idx, C2 outcome + price + idx,
    total PnL net of commission.

    Protective stop = TIGHTER of cat_SL distance and prior_level_SL.
    For "no-cat" (sentinel), this falls back to prior_level_SL.
    """
    n = len(highs)
    last = min(eod_idx, n - 1)
    if entry_idx >= n or last < entry_idx:
        return None
    sli_h = highs[entry_idx : last + 1]
    sli_l = lows[entry_idx : last + 1]
    sli_c = closes[entry_idx : last + 1]
    nbars = len(sli_h)

    if di == 1:
        cat_px = entry_px - cat_sl_pts
        cat_sl_px = max(cat_px, prior_sl_px)  # tighter wins
        tp_px = entry_px + TP_PTS
        be_px = entry_px + BE_OFFSET
    else:
        cat_px = entry_px + cat_sl_pts
        cat_sl_px = min(cat_px, prior_sl_px)  # tighter wins
        tp_px = entry_px - TP_PTS
        be_px = entry_px - BE_OFFSET

    c1_open = True
    c2_open = True
    c1_outcome = None
    c1_exit_px = None
    c1_exit_idx = None
    c2_outcome = None
    c2_exit_px = None
    c2_exit_idx = None
    c1_tp_at = -1   # second when C1 TP fired

    for s in range(nbars):
        h = sli_h[s]; l = sli_l[s]
        # Determine if C2 BE is active this bar
        # BE active starting at c1_tp_at + BE_DELAY
        c2_be_active = (c1_tp_at >= 0 and s >= c1_tp_at + BE_DELAY)

        # ----- Conservative within-bar priority -----
        # 1) Cat-SL hit (long: l <= cat_sl_px) — applies to whichever
        #    contract still has cat_SL as its active stop.
        if di == 1:
            cat_hit = (l <= cat_sl_px)
        else:
            cat_hit = (h >= cat_sl_px)

        # C1 cat-SL (C1 always has cat_SL until TP)
        if c1_open and cat_hit:
            c1_open = False
            c1_outcome = "cat_loss"; c1_exit_px = cat_sl_px; c1_exit_idx = s

        # C2 cat-SL (only if BE not yet active)
        if c2_open and not c2_be_active and cat_hit:
            c2_open = False
            c2_outcome = "cat_loss"; c2_exit_px = cat_sl_px; c2_exit_idx = s

        # 2) C1 TP hit — only if C1 still open after cat check
        if c1_open:
            if di == 1:
                tp_hit = (h >= tp_px)
            else:
                tp_hit = (l <= tp_px)
            if tp_hit:
                c1_open = False
                c1_outcome = "tp"; c1_exit_px = tp_px; c1_exit_idx = s
                c1_tp_at = s

        # 3) C2 BE-stop (only if BE active and C2 still open)
        if c2_open and c2_be_active:
            if di == 1:
                be_hit = (l <= be_px)
            else:
                be_hit = (h >= be_px)
            if be_hit:
                c2_open = False
                c2_outcome = "be_stop"; c2_exit_px = be_px; c2_exit_idx = s

        # 4) C2 PT hit — only if C2 still open
        if c2_open:
            if di == 1:
                pt_hit = (h >= pt_px)
            else:
                pt_hit = (l <= pt_px)
            if pt_hit:
                c2_open = False
                c2_outcome = "win"; c2_exit_px = pt_px; c2_exit_idx = s

        if not c1_open and not c2_open:
            break

    # EOD-flat for any still-open
    if c1_open:
        c1_outcome = "eod_flat"
        c1_exit_px = float(sli_c[-1]); c1_exit_idx = nbars - 1
    if c2_open:
        c2_outcome = "eod_flat"
        c2_exit_px = float(sli_c[-1]); c2_exit_idx = nbars - 1

    # PnL net (per contract)
    c1_pnl = (c1_exit_px - entry_px) * di - COMMISSION_PTS
    c2_pnl = (c2_exit_px - entry_px) * di - COMMISSION_PTS

    # Take the LATER exit as chain "exit_idx" for skip-while-open
    last_exit_local = max(c1_exit_idx, c2_exit_idx)

    return {
        "c1_outcome": c1_outcome, "c1_pnl_pts": float(c1_pnl),
        "c1_exit_idx_global": entry_idx + c1_exit_idx,
        "c2_outcome": c2_outcome, "c2_pnl_pts": float(c2_pnl),
        "c2_exit_idx_global": entry_idx + c2_exit_idx,
        "total_pnl_pts": float(c1_pnl + c2_pnl),
        "total_pnl_dollars": float((c1_pnl + c2_pnl) * NQ_DOLLAR_PER_PT),
        "c1_tp_at": c1_tp_at,
        "exit_idx_global": entry_idx + last_exit_local,
    }


# ---------------- Trade harvesting (fixed chain on baseline) ----------------

def harvest_trades(year):
    """Load 1s, detect triggers, build chain on no-policy baseline,
    assign buckets. Returns list of dicts + arrays."""
    print(f"\n[{year}] loading & harvesting...")
    bars_1s = load_v0_1s(Path(f"data/raw/NQ_v0_1s_{year}.parquet"))
    bars_1s = annotate_sessions_1s(bars_1s)
    bars_1m = bars_1s[
        ["open", "high", "low", "close", "volume"]
    ].resample("1min", label="right", closed="right").agg({
        "open": "first", "high": "max", "low": "min",
        "close": "last", "volume": "sum"
    }).dropna(subset=["open", "high", "low", "close"])
    bars_1m = annotate_sessions_ct(bars_1m)
    triggers = detect_triggers_breakout(bars_1m)

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

    last_chain_exit = -1
    trades = []
    for tr in triggers:
        ts = pd.Timestamp(tr["bar_ts_close"])
        if ts.tz is None: ts = ts.tz_localize("UTC")
        else: ts = ts.tz_convert("UTC")
        e = map_1m_trigger_to_1s_entry(ts, ts_close_1s)
        if e < 0: continue
        if e <= last_chain_exit: continue
        di = tr["direction"]
        entry_px = float(opens[e])
        bp = sim_baseline_path(
            e, di, entry_px, float(tr["target"]),
            float(tr["stop"]), int(next_eod[e]),
            highs, lows, closes)
        if bp is None: continue
        last_chain_exit = bp["exit_idx_global"]
        if sessions[e] != "RTH":
            continue
        bucket = assign_bucket(
            bp["outcome"], bp["mfe_t"], bp["mae_t"], bp["max_mfe"])
        trades.append({
            "year": year,
            "entry_1s_idx": e,
            "entry_px": entry_px,
            "direction": di,
            "target": float(tr["target"]),
            "prior_sl": float(tr["stop"]),
            "eod_idx": int(next_eod[e]),
            "level_pair": tr["level_pair"],
            "group": assign_group(tr["level_pair"]),
            "bucket": bucket,
            "baseline_outcome": bp["outcome"],
            "baseline_max_mfe": bp["max_mfe"],
            "baseline_max_mae": bp["max_mae"],
        })
    print(f"  RTH trades on baseline chain: {len(trades):,}")
    return trades, highs, lows, closes


# ---------------- Per-cell sweep ----------------

def sweep(trades, year_arrays):
    """Run sweep per group × cat_SL. Returns list of cell rows."""
    rows = []
    for grp_label, cat_grid in CAT_GRIDS.items():
        gt = [t for t in trades if t["group"] == grp_label]
        if not gt: continue
        for cat_pts in cat_grid:
            # Per-trade simulation
            per_trade = []
            for t in gt:
                h, l, c = year_arrays[t["year"]]
                r = sim_2contract(
                    t["entry_1s_idx"], t["direction"], t["entry_px"],
                    t["target"], t["prior_sl"], t["eod_idx"],
                    cat_pts, h, l, c)
                if r is None: continue
                per_trade.append({
                    "year": t["year"], "bucket": t["bucket"],
                    "direction": t["direction"],
                    **r,
                })
            df = pd.DataFrame(per_trade)
            cat_label = ("no-cat" if cat_pts >= NO_CAT_SENTINEL
                         else f"{cat_pts:g}")

            # Aggregate cell
            n = len(df)
            if n == 0: continue
            row = {
                "group": grp_label,
                "cat_sl": cat_label,
                "n": n,
                "c1_tp_rate":
                    float((df["c1_outcome"] == "tp").mean()),
                "c1_cat_rate":
                    float((df["c1_outcome"] == "cat_loss").mean()),
                "c2_pt_rate":
                    float((df["c2_outcome"] == "win").mean()),
                "c2_be_rate":
                    float((df["c2_outcome"] == "be_stop").mean()),
                "c2_cat_rate":
                    float((df["c2_outcome"] == "cat_loss").mean()),
                "c2_eod_rate":
                    float((df["c2_outcome"] == "eod_flat").mean()),
                "mean_pnl_dollars":
                    float(df["total_pnl_dollars"].mean()),
                "total_pnl_dollars":
                    float(df["total_pnl_dollars"].sum()),
            }
            # Per-year split
            for yr in (2024, 2025):
                sub = df[df["year"] == yr]
                if len(sub):
                    row[f"y{yr}_total_$"] = float(
                        sub["total_pnl_dollars"].sum())
                    row[f"y{yr}_mean_$"] = float(
                        sub["total_pnl_dollars"].mean())
                    row[f"y{yr}_n"] = len(sub)
            # Per-bucket
            for bk in ("win_clean", "win_vshape",
                       "loss_runthenbreak", "loss_quick"):
                sub = df[df["bucket"] == bk]
                if len(sub):
                    row[f"{bk}_n"] = len(sub)
                    row[f"{bk}_mean_$"] = float(
                        sub["total_pnl_dollars"].mean())
                    row[f"{bk}_total_$"] = float(
                        sub["total_pnl_dollars"].sum())
                    # C1 TP rate within this bucket
                    row[f"{bk}_c1tp_pct"] = float(
                        100 * (sub["c1_outcome"] == "tp").mean())
                    row[f"{bk}_c2pt_pct"] = float(
                        100 * (sub["c2_outcome"] == "win").mean())
                    row[f"{bk}_c2be_pct"] = float(
                        100 * (sub["c2_outcome"] == "be_stop").mean())
            rows.append(row)
    return rows


# ---------------- Main ----------------

def main():
    t0 = time.time()
    all_trades = []
    year_arrays = {}
    for year in (2024, 2025):
        trades, h, l, c = harvest_trades(year)
        year_arrays[year] = (h, l, c)
        all_trades.extend(trades)
    print(f"\nTotal RTH trades: {len(all_trades):,}")

    # Confirm bucket counts
    print(f"\nBucket distribution:")
    df_t = pd.DataFrame(all_trades)
    for grp in ("A_25pt", "B_14_15pt", "C_10_11pt"):
        g = df_t[df_t["group"] == grp]
        print(f"  [{grp}] n={len(g):,}")
        for bk in ("win_clean", "win_vshape", "win_no_arm",
                   "loss_runthenbreak", "loss_quick", "timed_out"):
            sub = g[g["bucket"] == bk]
            if len(sub):
                print(f"    {bk:<22} n={len(sub):>5,} "
                      f"({100*len(sub)/len(g):>5.1f}%)")

    # Run sweep
    print(f"\n{'='*80}\nSWEEP: 2-contract TP+5 / BE on C2, "
          f"cat_SL grid per group\n{'='*80}")
    rows = sweep(all_trades, year_arrays)
    df_cells = pd.DataFrame(rows)
    df_cells.to_csv(OUT / "2contract_tp5_be_sweep.csv", index=False)

    # Print per-cell summary table
    for grp in ("A_25pt", "B_14_15pt", "C_10_11pt"):
        g = df_cells[df_cells["group"] == grp]
        if g.empty: continue
        print(f"\n[{grp}] cell summary:")
        print(f"  {'cat_SL':<8} {'n':>6} "
              f"{'c1tp%':>6} {'c2pt%':>6} {'c2be%':>6} {'c2cat%':>7} "
              f"{'$/tr':>9} {'total $':>14} "
              f"{'2024 $':>11} {'2025 $':>11}")
        for _, r in g.iterrows():
            print(f"  {str(r['cat_sl']):<8} {int(r['n']):>6,} "
                  f"{100*r['c1_tp_rate']:>5.1f}% "
                  f"{100*r['c2_pt_rate']:>5.1f}% "
                  f"{100*r['c2_be_rate']:>5.1f}% "
                  f"{100*r['c2_cat_rate']:>6.1f}% "
                  f"{r['mean_pnl_dollars']:>+8.2f} "
                  f"{r['total_pnl_dollars']:>+13,.0f} "
                  f"{r.get('y2024_total_$', 0):>+10,.0f} "
                  f"{r.get('y2025_total_$', 0):>+10,.0f}")

    # Best cell per group (positive in BOTH years)
    print(f"\n{'='*80}\nBEST CELL PER GROUP (positive in BOTH 2024 AND "
          f"2025)\n{'='*80}")
    for grp in ("A_25pt", "B_14_15pt", "C_10_11pt"):
        g = df_cells[df_cells["group"] == grp].copy()
        if g.empty: continue
        g["pass_both"] = ((g["y2024_total_$"] > 0) &
                          (g["y2025_total_$"] > 0))
        passers = g[g["pass_both"]]
        if len(passers) == 0:
            print(f"\n[{grp}] NO cells positive in both years.")
            best = g.nlargest(1, "total_pnl_dollars").iloc[0]
            print(f"  (best by total): cat_SL={best['cat_sl']} "
                  f"$/tr={best['mean_pnl_dollars']:+.2f} "
                  f"2024=${best['y2024_total_$']:+,.0f} "
                  f"2025=${best['y2025_total_$']:+,.0f}")
            continue
        best = passers.nlargest(1, "mean_pnl_dollars").iloc[0]
        print(f"\n[{grp}] {len(passers)}/{len(g)} cells positive "
              f"in both years")
        print(f"  best: cat_SL={best['cat_sl']} "
              f"$/tr={best['mean_pnl_dollars']:+.2f} "
              f"total ${best['total_pnl_dollars']:+,.0f} "
              f"(2024 ${best['y2024_total_$']:+,.0f} / "
              f"2025 ${best['y2025_total_$']:+,.0f})")
        print(f"  per-bucket within best cell:")
        for bk in ("win_clean", "win_vshape",
                   "loss_runthenbreak", "loss_quick"):
            n = best.get(f"{bk}_n", 0)
            if not n or n == 0: continue
            print(f"    {bk:<20} n={int(n):>5,} "
                  f"$/tr={best[f'{bk}_mean_$']:+8.2f} "
                  f"C1TP={best[f'{bk}_c1tp_pct']:>5.1f}% "
                  f"C2PT={best[f'{bk}_c2pt_pct']:>5.1f}% "
                  f"C2BE={best[f'{bk}_c2be_pct']:>5.1f}% "
                  f"total ${best[f'{bk}_total_$']:+12,.0f}")

    print(f"\n[done] runtime: {time.time()-t0:.1f}s")
    print(f"\nSaved cell table: {OUT / '2contract_tp5_be_sweep.csv'}")


if __name__ == "__main__":
    main()
