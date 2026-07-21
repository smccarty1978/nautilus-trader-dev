"""2-contract TP=5 with TRAILING stop on C2 (instead of static BE+1tick).

POLICY
------
1. Enter 2 contracts at 1s after 1m trigger close.
2. Pre-arm protective stop (cat_SL or prior_level whichever tighter).
3. C1: limit TP at entry +/- 5 pts. When fires, C2 transitions to BE
   trailing stop after BE_DELAY (1 1s bar).
4. C2 BE trailing stop:
     initial = entry +/- 1 tick
     trails: max(initial, peak - trail_distance)
     where peak = best favorable price observed since entry
5. After arming, cat_SL is REMOVED (BE trail is the only stop on C2).
6. C2 PT = original PT (next-level - 2.5).
7. Within-bar priority: cat_SL > C1_TP > C2_trail_stop > C2_PT (conservative).
8. EOD-flat at 16:00 CT.

Sweep trail_distance = [1, 2, 3, 5] pts. Compare to static (trail=0)
baseline.
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

from studies.level_momentum_continuation.analyze_2contract_tp5_be import (
    sim_baseline_path, assign_bucket, harvest_trades,
    NQ_DOLLAR_PER_PT, COMMISSION_PTS, TICK_SIZE,
    TP_PTS, BE_OFFSET, BE_DELAY,
)

OUT = Path("studies/level_momentum_continuation/results_breakout")
OUT.mkdir(parents=True, exist_ok=True)

# Cat_SL per group (best from prior sweep)
CAT_SL_PER_GROUP = {
    "A_25pt": 8.0,
    "B_14_15pt": 6.0,
    "C_10_11pt": 8.0,
}

TRAIL_GRID = [0.0, 1.0, 2.0, 3.0, 5.0]   # 0 = static BE+1tick (baseline)


def sim_2contract_trailing(
    entry_idx, di, entry_px, pt_px, prior_sl_px, eod_idx,
    cat_sl_pts, trail_dist,
    highs, lows, closes,
):
    """2-contract sim with C2 trailing stop after C1 TP fires.
    trail_dist = 0 means static BE+1tick (matches original sim)."""
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
        cat_sl_px = max(cat_px, prior_sl_px)
        tp_px = entry_px + TP_PTS
        be_floor_px = entry_px + BE_OFFSET   # BE+1tick floor
    else:
        cat_px = entry_px + cat_sl_pts
        cat_sl_px = min(cat_px, prior_sl_px)
        tp_px = entry_px - TP_PTS
        be_floor_px = entry_px - BE_OFFSET

    c1_open = True
    c1_outcome = None; c1_exit_px = None; c1_exit_idx = None
    c2_open = True
    c2_outcome = None; c2_exit_px = None; c2_exit_idx = None
    c1_tp_at = -1
    c2_running_peak = entry_px      # best favorable price observed
    c2_trail_stop = be_floor_px     # initial floor

    for s in range(nbars):
        h = sli_h[s]; l = sli_l[s]
        c2_be_active = (c1_tp_at >= 0 and s >= c1_tp_at + BE_DELAY)

        # Update running peak (long: track high; short: track low)
        if di == 1:
            if h > c2_running_peak:
                c2_running_peak = h
        else:
            if l < c2_running_peak:
                c2_running_peak = l

        # If trailing active, update trail stop
        if c2_be_active and trail_dist > 0:
            if di == 1:
                trailed = c2_running_peak - trail_dist
                c2_trail_stop = max(c2_trail_stop, trailed)
            else:
                trailed = c2_running_peak + trail_dist
                c2_trail_stop = min(c2_trail_stop, trailed)
        # If trail_dist == 0, c2_trail_stop stays at be_floor_px (static)

        # 1) Cat-SL check (pre-arm only)
        if di == 1:
            cat_hit = (l <= cat_sl_px)
        else:
            cat_hit = (h >= cat_sl_px)
        if c1_open and cat_hit:
            c1_open = False
            c1_outcome = "cat_loss"
            c1_exit_px = cat_sl_px; c1_exit_idx = s
        if c2_open and not c2_be_active and cat_hit:
            c2_open = False
            c2_outcome = "cat_loss"
            c2_exit_px = cat_sl_px; c2_exit_idx = s

        # 2) C1 TP
        if c1_open:
            tp_hit = (h >= tp_px) if di == 1 else (l <= tp_px)
            if tp_hit:
                c1_open = False
                c1_outcome = "tp"; c1_exit_px = tp_px; c1_exit_idx = s
                c1_tp_at = s

        # 3) C2 BE/trail-stop (only if BE active)
        if c2_open and c2_be_active:
            if di == 1:
                stop_hit = (l <= c2_trail_stop)
            else:
                stop_hit = (h >= c2_trail_stop)
            if stop_hit:
                c2_open = False
                # Label outcome: be_stop if trail still at floor;
                # else "trail_stop"
                if c2_trail_stop == be_floor_px:
                    c2_outcome = "be_stop"
                else:
                    c2_outcome = "trail_stop"
                c2_exit_px = c2_trail_stop; c2_exit_idx = s

        # 4) C2 PT
        if c2_open:
            pt_hit = (h >= pt_px) if di == 1 else (l <= pt_px)
            if pt_hit:
                c2_open = False
                c2_outcome = "win"; c2_exit_px = pt_px; c2_exit_idx = s

        if not c1_open and not c2_open:
            break

    if c1_open:
        c1_outcome = "eod_flat"
        c1_exit_px = float(sli_c[-1]); c1_exit_idx = nbars - 1
    if c2_open:
        c2_outcome = "eod_flat"
        c2_exit_px = float(sli_c[-1]); c2_exit_idx = nbars - 1

    c1_pnl = (c1_exit_px - entry_px) * di - COMMISSION_PTS
    c2_pnl = (c2_exit_px - entry_px) * di - COMMISSION_PTS
    last_local = max(c1_exit_idx, c2_exit_idx)

    return {
        "c1_outcome": c1_outcome, "c1_pnl_pts": float(c1_pnl),
        "c2_outcome": c2_outcome, "c2_pnl_pts": float(c2_pnl),
        "total_pnl_pts": float(c1_pnl + c2_pnl),
        "total_pnl_dollars": float((c1_pnl + c2_pnl) * NQ_DOLLAR_PER_PT),
        "c2_trail_final": float(c2_trail_stop),
        "exit_idx_global": entry_idx + last_local,
    }


def main():
    t0 = time.time()
    all_trades = []
    year_arrays = {}
    for year in (2024, 2025):
        trades, h, l, c = harvest_trades(year)
        year_arrays[year] = (h, l, c)
        all_trades.extend(trades)
    print(f"\nTotal RTH trades: {len(all_trades):,}\n")

    rows = []
    for grp in ("A_25pt", "B_14_15pt", "C_10_11pt"):
        gt = [t for t in all_trades if t["group"] == grp]
        if not gt: continue
        cat = CAT_SL_PER_GROUP[grp]
        print(f"\n{'='*78}\n[{grp}] cat_SL={cat}, n={len(gt):,}")
        print(f"{'='*78}")
        for trail in TRAIL_GRID:
            tag = ("static_BE" if trail == 0 else f"trail_{trail:g}")
            per_trade = []
            for t in gt:
                h, l, c = year_arrays[t["year"]]
                r = sim_2contract_trailing(
                    t["entry_1s_idx"], t["direction"], t["entry_px"],
                    t["target"], t["prior_sl"], t["eod_idx"],
                    cat, trail, h, l, c)
                if r is None: continue
                per_trade.append({
                    "year": t["year"], "bucket": t["bucket"],
                    **r,
                })
            df = pd.DataFrame(per_trade)
            n = len(df)
            n_c1tp = int((df["c1_outcome"] == "tp").sum())
            n_c2pt = int((df["c2_outcome"] == "win").sum())
            n_c2be = int((df["c2_outcome"] == "be_stop").sum())
            n_c2trail = int((df["c2_outcome"] == "trail_stop").sum())
            n_c2cat = int((df["c2_outcome"] == "cat_loss").sum())
            n_c2eod = int((df["c2_outcome"] == "eod_flat").sum())
            mean_pnl = float(df["total_pnl_dollars"].mean())
            total_pnl = float(df["total_pnl_dollars"].sum())
            y2024 = float(df[df["year"]==2024]["total_pnl_dollars"].sum())
            y2025 = float(df[df["year"]==2025]["total_pnl_dollars"].sum())
            print(f"\n  {tag:<14} | $/tr={mean_pnl:>+6.2f}  total ${total_pnl:>+10,.0f}  "
                  f"(2024 ${y2024:>+8,.0f} / 2025 ${y2025:>+8,.0f})")
            print(f"     C1: TP={100*n_c1tp/n:>4.1f}%   "
                  f"C2: PT={100*n_c2pt/n:>4.1f}%  BE={100*n_c2be/n:>4.1f}%  "
                  f"trail={100*n_c2trail/n:>4.1f}%  cat={100*n_c2cat/n:>4.1f}%")
            # Per-bucket impact
            for bk in ("win_clean", "win_vshape",
                       "loss_runthenbreak", "loss_quick"):
                sub = df[df["bucket"] == bk]
                if len(sub) == 0: continue
                bk_mean = float(sub["total_pnl_dollars"].mean())
                bk_total = float(sub["total_pnl_dollars"].sum())
                print(f"       {bk:<22} n={len(sub):>5,} "
                      f"$/tr={bk_mean:>+8.2f}  total ${bk_total:>+11,.0f}")
            rows.append({
                "group": grp, "trail": trail, "tag": tag, "n": n,
                "mean_pnl_$": mean_pnl, "total_$": total_pnl,
                "y2024_$": y2024, "y2025_$": y2025,
                "c1_tp_pct": 100*n_c1tp/n,
                "c2_pt_pct": 100*n_c2pt/n,
                "c2_be_pct": 100*n_c2be/n,
                "c2_trail_pct": 100*n_c2trail/n,
                "c2_cat_pct": 100*n_c2cat/n,
            })
    pd.DataFrame(rows).to_csv(
        OUT / "2contract_trailing_sweep.csv", index=False)
    print(f"\n[done] runtime: {time.time()-t0:.1f}s")
    print(f"saved: {OUT / '2contract_trailing_sweep.csv'}")


if __name__ == "__main__":
    main()
