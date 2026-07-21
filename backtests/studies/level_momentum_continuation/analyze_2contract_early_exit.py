"""2-contract / TP+5 / BE+1tick / cat_SL  +  MFE-based early exit.

POLICY
------
Same 2-contract base as analyze_2contract_tp5_be.py, PLUS:

  Early-exit gate: at second T = T_thresh after entry, if running MFE
  has not yet reached MFE_thresh, exit any still-open contracts at the
  CLOSE of the T_thresh-th 1s bar. ("If you can't muster +X within Ys,
  cut and move on.")

Within-bar priority at second s:
  1) Cat-SL hit (closes any still-open contract at cat_SL price)
  2) C1 TP (locks in C1 at +5; arms BE+1tick on C2 from s+BE_DELAY)
  3) C2 BE-stop (only if BE active)
  4) C2 PT
  5) NEW: at s == T_thresh, if running MFE < MFE_thresh, close any
     still-open contracts at sli_c[s] (close of bar s)

Cat_SL fixed per group at the best from prior sweep:
  A_25pt:    cat_SL = 8 pts
  B_14_15pt: cat_SL = 6 pts
  C_10_11pt: cat_SL = 8 pts

Sweep grid per group: T_thresh × MFE_thresh = 5 × 5 cells.
Plus a "no-early-exit" baseline for reference.

Population: NQ.v.0 RTH 2024+2025 breakout-filter trades.
Chain: fixed on no-policy baseline.
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
from studies.level_momentum_continuation.analyze_2contract_tp5_be import (
    sim_baseline_path, assign_bucket,
    NQ_DOLLAR_PER_PT, COMMISSION_PTS, TICK_SIZE,
    TP_PTS, BE_OFFSET, BE_DELAY, NO_CAT_SENTINEL,
    ARM_THRESHOLD, CLEAN_MAE_CAP,
)

OUT = Path("studies/level_momentum_continuation/results_breakout")
OUT.mkdir(parents=True, exist_ok=True)

# Fixed per-group cat_SL (best from prior sweep)
CAT_SL_PER_GROUP = {
    "A_25pt": 8.0,
    "B_14_15pt": 6.0,
    "C_10_11pt": 8.0,
}

T_GRID = [5, 10, 15, 20, 30]              # seconds
MFE_GRID = [0.5, 1.0, 1.5, 2.0, 2.5]      # pts


def sim_2contract_early_exit(
    entry_idx, di, entry_px, pt_px, prior_sl_px, eod_idx,
    cat_sl_pts, t_thresh, mfe_thresh,
    highs, lows, closes,
):
    """Same as sim_2contract, plus early-exit at t_thresh if MFE
    hasn't reached mfe_thresh by then. mfe_thresh = None for baseline
    (no early-exit)."""
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
        be_px = entry_px + BE_OFFSET
    else:
        cat_px = entry_px + cat_sl_pts
        cat_sl_px = min(cat_px, prior_sl_px)
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
    c1_tp_at = -1
    running_mfe = 0.0

    for s in range(nbars):
        h = sli_h[s]; l = sli_l[s]
        # Update running_mfe
        if di == 1:
            cur_mfe = h - entry_px
        else:
            cur_mfe = entry_px - l
        if cur_mfe > running_mfe:
            running_mfe = cur_mfe

        c2_be_active = (c1_tp_at >= 0 and s >= c1_tp_at + BE_DELAY)

        # 1) Cat-SL
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

        # 3) C2 BE-stop
        if c2_open and c2_be_active:
            be_hit = (l <= be_px) if di == 1 else (h >= be_px)
            if be_hit:
                c2_open = False
                c2_outcome = "be_stop"
                c2_exit_px = be_px; c2_exit_idx = s

        # 4) C2 PT
        if c2_open:
            pt_hit = (h >= pt_px) if di == 1 else (l <= pt_px)
            if pt_hit:
                c2_open = False
                c2_outcome = "win"; c2_exit_px = pt_px; c2_exit_idx = s

        # 5) Early-exit at T_thresh (only if mfe_thresh provided)
        if (mfe_thresh is not None
                and s == t_thresh
                and running_mfe < mfe_thresh):
            ex_px = float(sli_c[s])
            if c1_open:
                c1_open = False
                c1_outcome = "early_exit"
                c1_exit_px = ex_px; c1_exit_idx = s
            if c2_open:
                c2_open = False
                c2_outcome = "early_exit"
                c2_exit_px = ex_px; c2_exit_idx = s

        if not c1_open and not c2_open:
            break

    # EOD-flat for any still open
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
        "exit_idx_global": entry_idx + last_local,
    }


def harvest_trades(year):
    """Same harvesting as analyze_2contract_tp5_be."""
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
            "year": year, "entry_1s_idx": e, "entry_px": entry_px,
            "direction": di, "target": float(tr["target"]),
            "prior_sl": float(tr["stop"]),
            "eod_idx": int(next_eod[e]),
            "level_pair": tr["level_pair"],
            "group": assign_group(tr["level_pair"]),
            "bucket": bucket,
        })
    print(f"  RTH trades on baseline chain: {len(trades):,}")
    return trades, highs, lows, closes


def run_cell(trades, year_arrays, cat_sl_pts, t_thresh, mfe_thresh):
    rows = []
    for t in trades:
        h, l, c = year_arrays[t["year"]]
        r = sim_2contract_early_exit(
            t["entry_1s_idx"], t["direction"], t["entry_px"],
            t["target"], t["prior_sl"], t["eod_idx"],
            cat_sl_pts, t_thresh, mfe_thresh, h, l, c)
        if r is None: continue
        rows.append({
            "year": t["year"], "bucket": t["bucket"],
            "direction": t["direction"], **r,
        })
    return pd.DataFrame(rows)


def aggregate(df, label):
    n = len(df)
    if n == 0: return None
    n_win_c2 = int((df["c2_outcome"] == "win").sum())
    n_be = int((df["c2_outcome"] == "be_stop").sum())
    n_cat = int((df["c1_outcome"] == "cat_loss").sum())
    n_early = int((df["c1_outcome"] == "early_exit").sum())
    n_c1tp = int((df["c1_outcome"] == "tp").sum())
    out = {
        "label": label, "n": n,
        "c1_tp_rate": n_c1tp / n,
        "c1_cat_rate": n_cat / n,
        "c1_early_rate": n_early / n,
        "c2_pt_rate": n_win_c2 / n,
        "c2_be_rate": n_be / n,
        "mean_pnl_$": float(df["total_pnl_dollars"].mean()),
        "total_$": float(df["total_pnl_dollars"].sum()),
    }
    for yr in (2024, 2025):
        sub = df[df["year"] == yr]
        if len(sub):
            out[f"y{yr}_total_$"] = float(sub["total_pnl_dollars"].sum())
            out[f"y{yr}_n"] = len(sub)
    for bk in ("win_clean", "win_vshape",
                "loss_runthenbreak", "loss_quick"):
        sub = df[df["bucket"] == bk]
        if len(sub):
            out[f"{bk}_n"] = len(sub)
            out[f"{bk}_mean_$"] = float(sub["total_pnl_dollars"].mean())
            out[f"{bk}_total_$"] = float(sub["total_pnl_dollars"].sum())
            out[f"{bk}_early_pct"] = float(
                100 * (sub["c1_outcome"] == "early_exit").mean())
    return out


def main():
    t0 = time.time()
    all_trades = []
    year_arrays = {}
    for year in (2024, 2025):
        trades, h, l, c = harvest_trades(year)
        year_arrays[year] = (h, l, c)
        all_trades.extend(trades)
    print(f"\nTotal RTH trades: {len(all_trades):,}\n")

    summary_rows = []
    for grp in ("A_25pt", "B_14_15pt", "C_10_11pt"):
        gt = [t for t in all_trades if t["group"] == grp]
        if not gt: continue
        cat = CAT_SL_PER_GROUP[grp]
        print(f"\n{'='*78}")
        print(f"[{grp}] cat_SL fixed at {cat} pts, n_trades={len(gt):,}")
        print(f"{'='*78}")

        # Baseline (no early exit)
        df0 = run_cell(gt, year_arrays, cat, t_thresh=-1, mfe_thresh=None)
        agg0 = aggregate(df0, "baseline_no_early_exit")
        agg0["group"] = grp
        agg0["t_thresh"] = "-"; agg0["mfe_thresh"] = "-"
        summary_rows.append(agg0)
        print(f"  baseline (no early exit): "
              f"n={agg0['n']:,} $/tr={agg0['mean_pnl_$']:+.2f} "
              f"total ${agg0['total_$']:+,.0f} "
              f"(2024 ${agg0.get('y2024_total_$',0):+,.0f} / "
              f"2025 ${agg0.get('y2025_total_$',0):+,.0f})")

        # Sweep
        cells = []
        for T in T_GRID:
            for M in MFE_GRID:
                df = run_cell(gt, year_arrays, cat, T, M)
                ag = aggregate(df, f"T{T}_M{M}")
                ag["group"] = grp
                ag["t_thresh"] = T; ag["mfe_thresh"] = M
                cells.append(ag)
                summary_rows.append(ag)

        # Pivot for heatmap
        cdf = pd.DataFrame(cells)
        # Mean $/trade pivot
        pivot_mean = cdf.pivot(index="mfe_thresh", columns="t_thresh",
                                       values="mean_pnl_$")
        pivot_total = cdf.pivot(index="mfe_thresh", columns="t_thresh",
                                         values="total_$")
        print(f"\n[{grp}] mean $/trade  (rows=MFE_thresh, cols=T_thresh)")
        print(pivot_mean.round(2).to_string())
        print(f"\n[{grp}] total $       (rows=MFE_thresh, cols=T_thresh)")
        print(pivot_total.round(0).to_string())

        # Top 3 cells by total
        print(f"\n[{grp}] top 3 cells by total $:")
        top = cdf.nlargest(3, "total_$")
        for _, r in top.iterrows():
            y24 = r.get("y2024_total_$", 0)
            y25 = r.get("y2025_total_$", 0)
            tag = "✓" if (y24 > 0 and y25 > 0) else " "
            print(f"  T={int(r['t_thresh']):>3}s MFE={r['mfe_thresh']:>3.1f} "
                  f"| $/tr={r['mean_pnl_$']:+.2f} "
                  f"total ${r['total_$']:+,.0f} "
                  f"| 2024 ${y24:+,.0f}  2025 ${y25:+,.0f}  {tag}")

        # Best cell positive in BOTH years
        passers = [c for c in cells
                   if c.get("y2024_total_$", -1) > 0
                   and c.get("y2025_total_$", -1) > 0]
        if passers:
            best = max(passers, key=lambda x: x["mean_pnl_$"])
            print(f"\n[{grp}] BEST cell positive in both years: "
                  f"T={best['t_thresh']}s MFE={best['mfe_thresh']}")
            print(f"  $/tr={best['mean_pnl_$']:+.2f} "
                  f"total ${best['total_$']:+,.0f}")
            print(f"  Per-bucket within best cell:")
            for bk in ("win_clean", "win_vshape",
                       "loss_runthenbreak", "loss_quick"):
                n = best.get(f"{bk}_n", 0)
                if not n: continue
                print(f"    {bk:<22} n={int(n):>5,} "
                      f"$/tr={best[f'{bk}_mean_$']:+8.2f} "
                      f"early={best[f'{bk}_early_pct']:>5.1f}% "
                      f"total ${best[f'{bk}_total_$']:+12,.0f}")
        else:
            print(f"\n[{grp}] NO cells positive in both years")

    pd.DataFrame(summary_rows).to_csv(
        OUT / "2contract_early_exit_sweep.csv", index=False)
    print(f"\n[done] runtime: {time.time()-t0:.1f}s")
    print(f"saved: {OUT / '2contract_early_exit_sweep.csv'}")


if __name__ == "__main__":
    main()
