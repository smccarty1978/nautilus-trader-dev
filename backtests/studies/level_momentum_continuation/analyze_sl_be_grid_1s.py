"""SL x BE grid at 1s precision (NT-realistic).

Re-runs the SL/BE grid with:
  - 1m Goldilocks triggers
  - 1s execution (BE arming, BE-stop, cat-stop, target, EOD)
  - BE stop placed at entry +1 tick (favorable side, covers commission)
  - BE stop active starting bar AFTER arming (delay=1)
  - Skip-while-open at 1s precision
  - EOD flat at 16:00 CT

Grid:
  - SL_PTS: 5, 7.5, 10, 12.5, 15, 20, 25, 30, no-cat
  - BE_PTS: 0 (no BE), 2.5, 5, 7.5, 10, 12.5

For each cell, re-runs population from scratch (skip-while-open
chain depends on exit times which depend on SL/BE).
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
    load_v0_1s, detect_triggers, annotate_sessions_ct,
)
from studies.level_momentum_continuation.analyze_1s_precision import (
    annotate_sessions_1s, filter_roll_window_1s,
    map_1m_trigger_to_1s_entry, precompute_eod_1s,
)

OUT = Path(
    "studies/level_momentum_continuation/results_sl_be_grid_1s")
OUT.mkdir(parents=True, exist_ok=True)

COMMISSION_PTS = 0.25
NQ_DOLLAR_PER_PT = 20.0
TICK_SIZE = 0.25
BE_STOP_DELAY_BARS = 1
BE_STOP_OFFSET_TICKS = 1
NO_CAT_SENTINEL = 9999.0

SL_GRID = [5.0, 7.5, 10.0, 12.5, 15.0, 20.0, 25.0, 30.0,
                NO_CAT_SENTINEL]
BE_GRID = [0.0, 2.5, 5.0, 7.5, 10.0, 12.5]


def simulate_trade_1s(entry_1s_idx, di, entry_px, target,
                            sl_px, be_px, be_threshold, eod_idx,
                            opens_1s, highs_1s, lows_1s,
                            closes_1s):
    """Vectorized single-trade simulation using 1s bars.

    be_threshold = inf or 0 means "never arm" (caller's choice
    for no-BE configs).
    """
    n = len(opens_1s)
    last = min(eod_idx, n - 1)
    if entry_1s_idx >= n: return None
    if last < entry_1s_idx: return None

    sli_h = highs_1s[entry_1s_idx : last + 1]
    sli_l = lows_1s[entry_1s_idx : last + 1]
    sli_c = closes_1s[entry_1s_idx : last + 1]
    nbars = len(sli_h)

    if di == 1:
        running_mfe = np.maximum.accumulate(sli_h - entry_px)
        be_arm_mask = (running_mfe >= be_threshold) if (
            be_threshold > 0 and np.isfinite(be_threshold)
        ) else None
        if be_arm_mask is not None and be_arm_mask.any():
            be_armed_at = int(np.argmax(be_arm_mask))
        else:
            be_armed_at = -1
        cat_hit = sli_l <= sl_px
        cat_idx = int(np.argmax(cat_hit)) if cat_hit.any() else -1
        tgt_hit = sli_h >= target
        tgt_idx = int(np.argmax(tgt_hit)) if tgt_hit.any() else -1
        if be_armed_at >= 0:
            start = be_armed_at + BE_STOP_DELAY_BARS
            if start < nbars:
                bs_hit = sli_l[start:] <= be_px
                be_idx = (start + int(np.argmax(bs_hit))
                                if bs_hit.any() else -1)
            else:
                be_idx = -1
        else:
            be_idx = -1
    else:
        running_mfe = np.maximum.accumulate(entry_px - sli_l)
        be_arm_mask = (running_mfe >= be_threshold) if (
            be_threshold > 0 and np.isfinite(be_threshold)
        ) else None
        if be_arm_mask is not None and be_arm_mask.any():
            be_armed_at = int(np.argmax(be_arm_mask))
        else:
            be_armed_at = -1
        cat_hit = sli_h >= sl_px
        cat_idx = int(np.argmax(cat_hit)) if cat_hit.any() else -1
        tgt_hit = sli_l <= target
        tgt_idx = int(np.argmax(tgt_hit)) if tgt_hit.any() else -1
        if be_armed_at >= 0:
            start = be_armed_at + BE_STOP_DELAY_BARS
            if start < nbars:
                bs_hit = sli_h[start:] >= be_px
                be_idx = (start + int(np.argmax(bs_hit))
                                if bs_hit.any() else -1)
            else:
                be_idx = -1
        else:
            be_idx = -1

    candidates = []
    if cat_idx >= 0:
        if be_armed_at == -1 or cat_idx < be_armed_at:
            candidates.append((cat_idx, "cat_loss", sl_px))
    if be_idx >= 0:
        candidates.append((be_idx, "be_stop", be_px))
    if tgt_idx >= 0:
        candidates.append((tgt_idx, "win", target))

    if not candidates:
        outcome = "eod_flat"
        exit_idx_in_slice = nbars - 1
        exit_px = sli_c[-1]
    else:
        candidates.sort(key=lambda x: (
            x[0],
            0 if x[1] == "cat_loss"
            else (1 if x[1] == "be_stop" else 2)))
        exit_idx_in_slice, outcome, exit_px = candidates[0]

    pnl_gross = (exit_px - entry_px) * di
    return {
        "outcome": outcome,
        "exit_idx_global": entry_1s_idx + exit_idx_in_slice,
        "pnl_net": pnl_gross - COMMISSION_PTS,
    }


def run_cell(triggers, ts_close_1s_pd, opens_1s, highs_1s,
                  lows_1s, closes_1s, next_eod, sl_pts, be_pts):
    """Run one (sl_pts, be_pts) cell with skip-while-open."""
    be_threshold = float('inf') if be_pts == 0 else float(be_pts)
    be_off = BE_STOP_OFFSET_TICKS * TICK_SIZE
    chains = []
    last_chain_exit_1s = -1
    for tr in triggers:
        ts = (pd.Timestamp(tr.bar_ts_close).tz_convert("UTC")
              if pd.Timestamp(tr.bar_ts_close).tz is not None
              else pd.Timestamp(tr.bar_ts_close, tz="UTC"))
        e1s = map_1m_trigger_to_1s_entry(ts, ts_close_1s_pd)
        if e1s < 0: continue
        if e1s <= last_chain_exit_1s: continue
        di = tr.direction
        entry_px = float(opens_1s[e1s])
        sl_px = (entry_px - sl_pts) if di == 1 else (entry_px + sl_pts)
        be_px = (entry_px + be_off) if di == 1 else (entry_px - be_off)
        target = float(tr.target)
        eod_idx = int(next_eod[e1s])
        r = simulate_trade_1s(e1s, di, entry_px, target,
                                       sl_px, be_px, be_threshold,
                                       eod_idx,
                                       opens_1s, highs_1s,
                                       lows_1s, closes_1s)
        if r is None: continue
        chains.append(r)
        last_chain_exit_1s = r["exit_idx_global"]
    return chains


def main():
    t0 = time.time()
    all_results = {}

    for year in (2024, 2025):
        print(f"\n{'='*60}\n[{year}] loading 1s bars + triggers...")
        bars_1s = load_v0_1s(
            Path(f"data/raw/NQ_v0_1s_{year}.parquet"))
        bars_1s = annotate_sessions_1s(bars_1s)
        bars_1s = filter_roll_window_1s(bars_1s, 3)

        bars_1m = bars_1s[
            ["open", "high", "low", "close", "volume"]
        ].resample("1min", label="right",
                          closed="right").agg({
            "open": "first", "high": "max",
            "low": "min", "close": "last",
            "volume": "sum"}).dropna(
            subset=["open", "high", "low", "close"])
        bars_1m = annotate_sessions_ct(bars_1m)
        bars_1m_reset = bars_1m.reset_index(drop=False)
        triggers = detect_triggers(bars_1m_reset)
        print(f"  {len(triggers):,} triggers")

        bars_1s_reset = bars_1s.reset_index(drop=False)
        opens_1s = bars_1s_reset["open"].values
        highs_1s = bars_1s_reset["high"].values
        lows_1s = bars_1s_reset["low"].values
        closes_1s = bars_1s_reset["close"].values
        ts_close_1s_pd = pd.DatetimeIndex(
            bars_1s_reset["ts_close"])
        if ts_close_1s_pd.tz is None:
            ts_close_1s_pd = ts_close_1s_pd.tz_localize("UTC")
        else:
            ts_close_1s_pd = ts_close_1s_pd.tz_convert("UTC")
        next_eod = precompute_eod_1s(bars_1s_reset)

        rows = []
        for sl in SL_GRID:
            for be in BE_GRID:
                t1 = time.time()
                chains = run_cell(triggers, ts_close_1s_pd,
                                          opens_1s, highs_1s, lows_1s,
                                          closes_1s, next_eod, sl, be)
                df = pd.DataFrame(chains)
                n = len(df)
                if n == 0: continue
                n_w = int((df["outcome"] == "win").sum())
                n_be = int((df["outcome"] == "be_stop").sum())
                n_cat = int((df["outcome"] == "cat_loss").sum())
                n_eod = int((df["outcome"] == "eod_flat").sum())
                mean_pnl = float(df["pnl_net"].mean())
                total_pnl = float(df["pnl_net"].sum())
                annual = total_pnl * NQ_DOLLAR_PER_PT
                sl_label = ("no-cat" if sl == NO_CAT_SENTINEL
                                else f"{sl:.1f}")
                be_label = ("no-BE" if be == 0 else f"{be:.1f}")
                rows.append({
                    "sl_pts": sl_label, "be_pts": be_label,
                    "n": n,
                    "win_pct": n_w / n,
                    "be_stop_pct": n_be / n,
                    "cat_pct": n_cat / n,
                    "eod_pct": n_eod / n,
                    "mean_pnl_net": mean_pnl,
                    "total_pnl_net": total_pnl,
                    "annual_dollars": annual,
                })
                print(
                    f"  [SL={sl_label:>6s} BE={be_label:>5s}] "
                    f"n={n:,} WR={100*n_w/n:5.1f}% "
                    f"BE={100*n_be/n:5.1f}% "
                    f"cat={100*n_cat/n:5.1f}% "
                    f"mean={mean_pnl:+.3f} "
                    f"ann=${annual:>+11,.0f} "
                    f"({time.time()-t1:.1f}s)")
        all_results[year] = pd.DataFrame(rows)
        all_results[year].to_csv(OUT / f"grid_1s_{year}.csv",
                                          index=False)

    # Build markdown report
    print(f"\n{'='*60}\nWriting report...")
    L = []
    L.append("# SL × BE Grid at 1s Precision\n")
    L.append("## Method\n")
    L.append(
        "- Triggers: 1m Goldilocks bars (V_A baseline)\n"
        "- Execution: 1s bars (BE arming + BE stop + cat stop + "
        "target + EOD)\n"
        f"- BE stop offset: +{BE_STOP_OFFSET_TICKS} tick "
        "(favorable side; covers commission)\n"
        f"- BE stop delay: {BE_STOP_DELAY_BARS} bar "
        "(NT-realistic; stop placed AFTER arm bar)\n"
        "- Skip-while-open at 1s precision\n"
        "- EOD flat at 16:00 CT\n"
        f"- Commission: {COMMISSION_PTS} pt round trip\n"
        f"- NQ multiplier: ${NQ_DOLLAR_PER_PT}/pt\n\n"
        "BE_PTS = 0 means no BE arming (only cat SL + target + EOD).\n"
        "SL = no-cat means no catastrophic stop (only BE + target + EOD).\n")

    for year in sorted(all_results.keys()):
        L.append(f"## {year} — annual $ grid\n")
        df = all_results[year]
        pivot = df.pivot(index="sl_pts", columns="be_pts",
                                 values="annual_dollars")
        # Order rows by SL_GRID
        sl_order = ["5.0", "7.5", "10.0", "12.5", "15.0",
                          "20.0", "25.0", "30.0", "no-cat"]
        be_order = ["no-BE", "2.5", "5.0", "7.5", "10.0",
                          "12.5"]
        pivot = pivot.reindex(index=sl_order,
                                       columns=be_order)
        max_val = float(pivot.values[
            ~pd.isnull(pivot.values)].max())
        L.append(f"Best annual $: **${max_val:,.0f}**")
        L.append("")
        L.append("| SL\\BE | " + " | ".join(be_order) + " |")
        L.append("|---|" + "|".join(["---"] * len(be_order))
                       + "|")
        for sl in sl_order:
            row_cells = []
            for be in be_order:
                v = pivot.loc[sl, be] if (sl in pivot.index
                                                  and be in pivot.columns) else None
                if pd.isna(v):
                    row_cells.append("—")
                else:
                    s = f"${v:+,.0f}"
                    if v == max_val:
                        s = f"**{s}**"
                    row_cells.append(s)
            L.append(f"| {sl} | " + " | ".join(row_cells) + " |")
        L.append("")

        L.append(f"## {year} — mean PnL net per trade\n")
        pivot2 = df.pivot(index="sl_pts", columns="be_pts",
                                  values="mean_pnl_net")
        pivot2 = pivot2.reindex(index=sl_order,
                                          columns=be_order)
        L.append("| SL\\BE | " + " | ".join(be_order) + " |")
        L.append("|---|" + "|".join(["---"] * len(be_order))
                       + "|")
        for sl in sl_order:
            row_cells = []
            for be in be_order:
                v = pivot2.loc[sl, be] if (sl in pivot2.index
                                                   and be in pivot2.columns) else None
                row_cells.append("—" if pd.isna(v)
                                       else f"{v:+.3f}")
            L.append(f"| {sl} | " + " | ".join(row_cells) + " |")
        L.append("")

        # Top 5 cells
        L.append(f"## {year} — top 5 cells (by annual $)\n")
        top5 = df.sort_values("annual_dollars",
                                       ascending=False).head(5)
        L.append("| SL | BE | n | WR | BE-stop | cat | mean PnL | annual $ |")
        L.append("|---|---|--:|--:|--:|--:|--:|--:|")
        for _, r in top5.iterrows():
            L.append(
                f"| {r['sl_pts']} | {r['be_pts']} | "
                f"{int(r['n']):,} | "
                f"{100*r['win_pct']:.1f}% | "
                f"{100*r['be_stop_pct']:.1f}% | "
                f"{100*r['cat_pct']:.1f}% | "
                f"{r['mean_pnl_net']:+.3f} | "
                f"${r['annual_dollars']:+,.0f} |")
        L.append("")

    p = OUT / "report_sl_be_grid_1s.md"
    p.write_text("\n".join(L), encoding="utf-8")
    print(f"\nReport: {p}")
    print(f"Total elapsed: {(time.time()-t0)/60:.1f} min")


if __name__ == "__main__":
    main()
