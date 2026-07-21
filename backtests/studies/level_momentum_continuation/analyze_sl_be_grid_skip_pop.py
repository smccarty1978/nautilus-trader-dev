"""SL × BE grid sweep on the FIXED skip-while-open population.

Takes the trades that survived skip-while-open (BE=2.5 + original
'one prior in sequence' stops). For each (SL, BE) combo,
re-simulates only the EXIT logic on those specific trades:

  - SL = "ORIG" → keep the original "one prior in sequence" stop
  - SL = number → replace stop with entry ± SL pts
  - BE = 0 → no BE rule
  - BE = X → after MFE >= X pt, move stop to entry

Ordering: BE-armed exit > SL > target. BE armed at end of bar K,
checked from K+1.

Reports per year + combined.
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


SKIP_DIR = Path(
    "studies/level_momentum_continuation/results_skip_while_open")
OUT = Path(
    "studies/level_momentum_continuation/results_skip_grid")
OUT.mkdir(parents=True, exist_ok=True)

SL_PTS_LIST = ["ORIG", 5.0, 7.5, 10.0, 12.5, 15.0, 20.0, 25.0,
                  30.0]
BE_PTS_LIST = [0.0, 2.5, 5.0, 7.5, 10.0]
COMMISSION_PTS = 0.25
NQ_DOLLAR_PER_PT = 20.0
MAX_BARS = 120


def resimulate_one(t, bars, sl_pts, be_threshold):
    """Re-simulate one trade with given SL and BE settings.
    Returns (new_outcome, new_pnl_gross)."""
    n = len(bars)
    ent = int(t["entry_idx"])
    last = min(ent + MAX_BARS - 1, n - 1)
    di = int(t["direction"])
    ep = float(t["entry_price"])
    tgt = float(t["target"])
    if sl_pts == "ORIG":
        stop = float(t["stop"])
    else:
        stop = ep - sl_pts if di == 1 else ep + sl_pts

    highs = bars["high"].values
    lows = bars["low"].values
    closes = bars["close"].values

    armed = False
    mfe_so_far = 0.0
    outcome = None
    exit_px = ep
    for k in range(ent, last + 1):
        h = highs[k]; l = lows[k]
        # 1. BE check
        if armed:
            if di == 1 and l <= ep:
                outcome = "be_stop"
                exit_px = ep
                break
            if di == -1 and h >= ep:
                outcome = "be_stop"
                exit_px = ep
                break
        # 2. SL check
        if di == 1 and l <= stop:
            outcome = "loss"
            exit_px = stop
            break
        if di == -1 and h >= stop:
            outcome = "loss"
            exit_px = stop
            break
        # 3. Target
        if di == 1 and h >= tgt:
            outcome = "win"
            exit_px = tgt
            break
        if di == -1 and l <= tgt:
            outcome = "win"
            exit_px = tgt
            break
        # 4. Update MFE; arm BE
        if be_threshold > 0:
            bar_mfe = (h - ep) if di == 1 else (ep - l)
            if bar_mfe > mfe_so_far:
                mfe_so_far = bar_mfe
            if not armed and mfe_so_far >= be_threshold:
                armed = True

    if outcome is None:
        outcome = "timed_out"
        exit_px = closes[last]

    return outcome, (exit_px - ep) * di


def stats_block(g):
    n = len(g)
    if n == 0: return {"n": 0}
    pnl = g["pnl_pts_net"]
    out = g["outcome"]
    return {
        "n": n,
        "win_rate": float((out == "win").mean()),
        "loss_rate": float((out == "loss").mean()),
        "be_stop_rate": float((out == "be_stop").mean()),
        "timed_out_rate": float((out == "timed_out").mean()),
        "mean_pnl_net": float(pnl.mean()),
        "median_pnl_net": float(pnl.median()),
        "total_pnl_net": float(pnl.sum()),
        "annual_dollars": float(
            pnl.sum() * NQ_DOLLAR_PER_PT),
    }


def fmt_p(v):
    if v is None or pd.isna(v): return "—"
    return f"{100*v:.1f}%"


def fmt_f(v, dp=2):
    if v is None or pd.isna(v): return "—"
    return f"{v:+.{dp}f}"


def fmt_d(v):
    if v is None or pd.isna(v): return "—"
    return f"${v:,.0f}"


def write_report(grid_per_year, best_per_cell):
    L = []
    L.append("# SL × BE Grid on Skip-While-Open Population\n")
    L.append("## Method\n")
    L.append(
        "Fixed population: takes the trades that survived "
        "skip-while-open (BE=2.5 + original 'one prior in seq' "
        "stops). For each (SL, BE) combo, re-simulates only the "
        "EXIT logic on those trade indices.\n\n"
        f"SL grid: {SL_PTS_LIST}\n"
        f"BE grid: {BE_PTS_LIST}\n"
        f"Commission: {COMMISSION_PTS} pt. "
        f"NQ multiplier: ${NQ_DOLLAR_PER_PT}/pt.\n\n"
        "Caveat: 'fixed population' means the trade SET was "
        "selected by the original BE=2.5 + level-structure stops. "
        "The SL / BE grid below tests alternative exits on those "
        "specific trade indices. The actual deployable population "
        "would shift if SL/BE changed (Option B), but this Option "
        "A view is faster and answers 'best exit for these "
        "trades'.\n")

    for year in sorted(grid_per_year.keys()):
        grid = grid_per_year[year]
        L.append(f"## {year} — overall grid\n")
        L.append("Mean PnL net by (SL, BE). Bold = max.\n")
        p = grid.pivot(index="sl", columns="be",
                              values="mean_pnl_net")
        L.append("| SL\\BE | " + " | ".join(
            f"X={c}" for c in p.columns) + " |")
        L.append("|---" * (len(p.columns) + 1) + "|")
        max_val = p.values.max()
        for sl, row in p.iterrows():
            cells = []
            for col in p.columns:
                v = row[col]
                cell = fmt_f(v, 3)
                if v == max_val: cell = f"**{cell}**"
                cells.append(cell)
            L.append(f"| {sl} | " + " | ".join(cells) + " |")
        L.append("")

        L.append(f"### {year} — Annual $ at each cell\n")
        p = grid.pivot(index="sl", columns="be",
                              values="annual_dollars")
        L.append("| SL\\BE | " + " | ".join(
            f"X={c}" for c in p.columns) + " |")
        L.append("|---" * (len(p.columns) + 1) + "|")
        max_val = p.values.max()
        for sl, row in p.iterrows():
            cells = []
            for col in p.columns:
                v = row[col]
                cell = fmt_d(v)
                if v == max_val: cell = f"**{cell}**"
                cells.append(cell)
            L.append(f"| {sl} | " + " | ".join(cells) + " |")
        L.append("")

    # Best per pair-session
    L.append("## Best (SL, BE) per (pair × session) — combined "
              "2-year totals\n")
    L.append("Sorted by mean PnL net.\n")
    L.append("| Pair | Session | n | Best SL | Best BE | "
             "Mean Net | Annual $ |")
    L.append("|---|---|--:|--:|--:|--:|--:|")
    for _, r in best_per_cell.sort_values(
            "mean_pnl_net", ascending=False).iterrows():
        L.append(
            f"| {r['level_pair']} | {r['entry_session']} | "
            f"{int(r['n']):,} | {r['best_sl']} | "
            f"{r['best_be']} | "
            f"{fmt_f(r['mean_pnl_net'], 3)} | "
            f"{fmt_d(r['annual_dollars'])} |")
    L.append("")

    p = OUT / "report_sl_be_grid_skip_pop.md"
    p.write_text("\n".join(L), encoding="utf-8")
    return p


def main():
    t0 = time.time()
    grid_per_year = {}
    per_cell_best_rows = []
    all_grid_per_cell = []

    for year in [2024, 2025]:
        print(f"\n[{year}] loading skip-while-open trades...")
        trades = pd.read_csv(SKIP_DIR / f"trades_skip_{year}.csv")
        print(f"  {len(trades):,} trades")
        print(f"[{year}] reloading bars...")
        parquet = Path(f"data/raw/NQ_v0_1s_{year}.parquet")
        bars_1s = load_v0_1s(parquet)
        bars_1m = resample_1s_to_1m(bars_1s)
        bars_1m = annotate_sessions_ct(bars_1m)
        # filter roll
        from studies.level_momentum_continuation.run_nq_2025 import (
            filter_roll_window,
        )
        bars_filt, _ = filter_roll_window(bars_1m, 3)
        bars_reset = bars_filt.reset_index(drop=False)

        # Sweep
        print(f"[{year}] sweeping SL × BE grid...")
        rows = []
        for sl in SL_PTS_LIST:
            for be in BE_PTS_LIST:
                t1 = time.time()
                outcomes = []
                pnls = []
                for _, t in trades.iterrows():
                    o, pnl = resimulate_one(
                        t, bars_reset, sl, be)
                    outcomes.append(o)
                    pnls.append(pnl)
                tmp = trades.copy()
                tmp["outcome"] = outcomes
                tmp["pnl_pts_net"] = (
                    np.array(pnls) - COMMISSION_PTS)
                s = stats_block(tmp)
                s["sl"] = sl
                s["be"] = be
                rows.append(s)
                # per-cell
                for keys, g in tmp.groupby(
                        ["level_pair", "entry_session"],
                        observed=True):
                    cs = stats_block(g)
                    cs["sl"] = sl
                    cs["be"] = be
                    cs["level_pair"] = keys[0]
                    cs["entry_session"] = keys[1]
                    cs["year"] = year
                    all_grid_per_cell.append(cs)
                print(f"  {year} sl={sl}, be={be} → mean "
                      f"{s['mean_pnl_net']:+.3f}, "
                      f"({time.time()-t1:.1f}s)")
        grid_per_year[year] = pd.DataFrame(rows)
        grid_per_year[year].to_csv(
            OUT / f"grid_overall_{year}.csv", index=False)

    # Per-cell combined across years
    pc = pd.DataFrame(all_grid_per_cell)
    pc.to_csv(OUT / "grid_per_cell_per_year.csv", index=False)

    # Combine across years for each cell × (sl, be)
    combined = (pc.groupby(
        ["level_pair", "entry_session", "sl", "be"],
        observed=True).agg(
            n=("n", "sum"),
            total_pnl_net=("total_pnl_net", "sum"),
        ).reset_index())
    combined["mean_pnl_net"] = (
        combined["total_pnl_net"] / combined["n"])
    combined["annual_dollars"] = (
        combined["total_pnl_net"] * NQ_DOLLAR_PER_PT / 2)
    # Best per cell
    best_rows = []
    for keys, g in combined.groupby(
            ["level_pair", "entry_session"], observed=True):
        if len(g) == 0: continue
        best = g.loc[g["mean_pnl_net"].idxmax()]
        best_rows.append({
            "level_pair": keys[0],
            "entry_session": keys[1],
            "n": int(best["n"]),
            "best_sl": best["sl"],
            "best_be": best["be"],
            "mean_pnl_net": float(best["mean_pnl_net"]),
            "annual_dollars": float(best["annual_dollars"]),
        })
    best_per_cell = pd.DataFrame(best_rows)
    best_per_cell.to_csv(
        OUT / "best_per_cell_combined.csv", index=False)
    combined.to_csv(OUT / "grid_per_cell_combined.csv",
                            index=False)

    print("\nWriting report...")
    rp = write_report(grid_per_year, best_per_cell)
    print(f"Report: {rp}")
    print(f"Total elapsed: {(time.time() - t0)/60:.1f} min")
    return 0


if __name__ == "__main__":
    sys.exit(main())
