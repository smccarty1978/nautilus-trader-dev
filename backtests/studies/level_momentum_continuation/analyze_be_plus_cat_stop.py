"""Combined catastrophic-SL × BE-stop grid sweep.

For each combination (cat_stop_pts Y, be_threshold X):
  - Cat stop (Y) replaces the original "one prior in sequence" stop:
      long stop = entry - Y; short stop = entry + Y
  - BE rule: after MFE >= X, move stop to entry. BE check happens
    BEFORE cat stop within the bar (BE-armed trades never hit cat
    once armed since BE is at entry and cat is past entry adverse).

Bar-by-bar logic per trade:
  For k from entry forward (max 120 bars):
    1. If BE armed AND price hits entry -> exit BE
    2. Else cat stop check (price reaches entry-Y for long, +Y short)
       -> exit at cat stop
    3. Target check (high>=target long, low<=target short) -> win
    4. Update MFE from bar OHLC; arm BE if MFE>=X (effective bar K+1)

Conservative ordering: cat stop wins ties within a bar (loss before
target). BE is armed at end of bar K, checked from bar K+1.

Outputs per (pair × session):
  - Best (Y, X) combo
  - Mean PnL net, total PnL, annual $
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


V0_PARQUET = Path("data/raw/NQ_v0_1s_2025.parquet")
SOURCE = Path(
    "studies/level_momentum_continuation/results_nq_2025/"
    "trades_with_first_bar.csv")
OUT = Path(
    "studies/level_momentum_continuation/results_nq_2025")

CAT_STOP_PTS = [5.0, 7.5, 10.0, 12.5, 15.0, 20.0, 25.0, 30.0]
BE_THRESHOLDS_PTS = [2.5, 5.0, 7.5, 10.0, 0.0]  # 0.0 = no BE
COMMISSION_PTS = 0.25
NQ_DOLLAR_PER_PT = 20.0
MAX_BARS = 120


def resimulate_be_plus_cat(trades: pd.DataFrame,
                                    bars_1m: pd.DataFrame,
                                    cat_stop_pts: float,
                                    be_threshold: float
                                    ) -> pd.DataFrame:
    bars = bars_1m.reset_index(drop=False)
    highs = bars["high"].values
    lows = bars["low"].values
    closes = bars["close"].values
    n_bars = len(bars)

    out = trades.copy().reset_index(drop=True)
    eidx = out["entry_idx"].astype(int).values
    d = out["direction"].astype(int).values
    ep = out["entry_price"].astype(float).values
    target = out["target"].astype(float).values

    n = len(out)
    new_outcome = np.empty(n, dtype=object)
    new_pnl_gross = np.zeros(n)

    for i in range(n):
        ent = eidx[i]
        last = min(ent + MAX_BARS - 1, n_bars - 1)
        di = d[i]
        epi = ep[i]
        tgt = target[i]
        # Cat stop replaces original stop
        if di == 1:
            cat_stop = epi - cat_stop_pts
        else:
            cat_stop = epi + cat_stop_pts

        armed = False
        mfe_so_far = 0.0
        outcome = None
        exit_px = epi

        for k in range(ent, last + 1):
            h = highs[k]; l = lows[k]
            # 1. BE stop (if armed)
            if armed:
                if di == 1 and l <= epi:
                    outcome = "be_stop"
                    exit_px = epi
                    break
                if di == -1 and h >= epi:
                    outcome = "be_stop"
                    exit_px = epi
                    break
            # 2. Cat stop
            if di == 1 and l <= cat_stop:
                outcome = "cat_loss"
                exit_px = cat_stop
                break
            if di == -1 and h >= cat_stop:
                outcome = "cat_loss"
                exit_px = cat_stop
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
                bar_mfe = (h - epi) if di == 1 else (epi - l)
                if bar_mfe > mfe_so_far:
                    mfe_so_far = bar_mfe
                if not armed and mfe_so_far >= be_threshold:
                    armed = True

        if outcome is None:
            outcome = "timed_out"
            exit_px = closes[last]

        new_outcome[i] = outcome
        new_pnl_gross[i] = (exit_px - epi) * di

    out["new_outcome"] = new_outcome
    out["new_pnl_gross"] = new_pnl_gross
    out["new_pnl_net"] = new_pnl_gross - COMMISSION_PTS
    return out


def stats(df: pd.DataFrame) -> dict:
    n = len(df)
    if n == 0: return {"n": 0}
    pnl = df["new_pnl_net"]
    out = df["new_outcome"]
    return {
        "n": n,
        "win_rate": float((out == "win").mean()),
        "be_stop_rate": float((out == "be_stop").mean()),
        "cat_loss_rate": float((out == "cat_loss").mean()),
        "timed_out_rate": float((out == "timed_out").mean()),
        "mean_pnl": float(pnl.mean()),
        "total_pnl": float(pnl.sum()),
        "annual_dollars": float(pnl.sum() * NQ_DOLLAR_PER_PT),
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


def write_report(grid_overall, best_per_cell,
                       full_grid_per_cell, n_combos):
    L = []
    L.append("# Catastrophic SL × BE-Stop Grid "
              "— Level Momentum\n")
    L.append("## Method\n")
    L.append(
        "Replaces the original 'one prior in sequence' stop with "
        "a fixed catastrophic SL (Y pts), combined with a BE-stop "
        "activation after MFE >= X pts.\n\n"
        f"Sweep grid: cat_stop_pts in {CAT_STOP_PTS}, "
        f"be_threshold in {BE_THRESHOLDS_PTS} "
        f"({n_combos} combinations per cell).\n\n"
        f"BE threshold = 0.0 means NO BE rule (cat stop only).\n\n"
        "Per-bar order: BE-armed exit -> cat stop -> target. "
        "BE armed at end of bar K, checked from bar K+1.\n\n"
        f"Commission: {COMMISSION_PTS} pts/trade. "
        f"NQ multiplier: ${NQ_DOLLAR_PER_PT}/pt.\n")

    L.append("## Overall grid (all pairs/sessions combined)\n")
    L.append("Mean PnL net by (cat stop, BE X). Highlight = max\n")
    # Pivot to a 2D table
    p = grid_overall.pivot(
        index="cat_stop_pts", columns="be_threshold",
        values="mean_pnl")
    L.append("| Cat\\BE | " + " | ".join(
        f"X={c}" for c in p.columns) + " |")
    L.append("|---" * (len(p.columns) + 1) + "|")
    max_val = p.values.max()
    for cat, row in p.iterrows():
        cells = []
        for col in p.columns:
            v = row[col]
            cell = fmt_f(v, 3)
            if v == max_val: cell = f"**{cell}**"
            cells.append(cell)
        L.append(f"| {cat} | " + " | ".join(cells) + " |")
    L.append("")

    L.append("## Annual $ at each grid cell (overall)\n")
    p = grid_overall.pivot(
        index="cat_stop_pts", columns="be_threshold",
        values="annual_dollars")
    L.append("| Cat\\BE | " + " | ".join(
        f"X={c}" for c in p.columns) + " |")
    L.append("|---" * (len(p.columns) + 1) + "|")
    max_val = p.values.max()
    for cat, row in p.iterrows():
        cells = []
        for col in p.columns:
            v = row[col]
            cell = fmt_d(v)
            if v == max_val: cell = f"**{cell}**"
            cells.append(cell)
        L.append(f"| {cat} | " + " | ".join(cells) + " |")
    L.append("")

    L.append("## Best (cat stop, BE) per (pair × session)\n")
    L.append("Sorted by mean PnL net.\n")
    L.append("| Pair | Session | n | Best Cat | Best BE | "
             "WR | BE% | CatLoss% | Mean Net | Annual $ |")
    L.append("|---|---|--:|--:|--:|--:|--:|--:|--:|--:|")
    s = best_per_cell.sort_values(
        "best_mean_pnl", ascending=False)
    for _, r in s.iterrows():
        L.append(
            f"| {r['level_pair']} | {r['entry_session']} | "
            f"{int(r['n']):,} | {r['best_cat']:.1f} | "
            f"{r['best_be']:.1f} | "
            f"{fmt_p(r['best_win_rate'])} | "
            f"{fmt_p(r['best_be_stop_rate'])} | "
            f"{fmt_p(r['best_cat_loss_rate'])} | "
            f"{fmt_f(r['best_mean_pnl'], 3)} | "
            f"{fmt_d(r['best_annual_dollars'])} |")
    L.append("")

    L.append("## Top deployable candidates "
              "(mean PnL > +$0.30/trade, n >= 1,000)\n")
    cands = best_per_cell[
        (best_per_cell["best_mean_pnl"] > 0.30) &
        (best_per_cell["n"] >= 1000)
    ].sort_values("best_mean_pnl", ascending=False)
    if cands.empty:
        L.append("None.\n")
    else:
        L.append("| Pair | Session | n | Cat | BE | WR | "
                 "Mean Net | Annual $ |")
        L.append("|---|---|--:|--:|--:|--:|--:|--:|")
        for _, r in cands.iterrows():
            L.append(
                f"| {r['level_pair']} | {r['entry_session']} | "
                f"{int(r['n']):,} | {r['best_cat']:.1f} | "
                f"{r['best_be']:.1f} | "
                f"{fmt_p(r['best_win_rate'])} | "
                f"{fmt_f(r['best_mean_pnl'], 3)} | "
                f"{fmt_d(r['best_annual_dollars'])} |")
        L.append("")
        total_n = int(cands["n"].sum())
        total_dollars = cands["best_annual_dollars"].sum()
        L.append(f"\n**Combined portfolio**: "
                  f"{total_n:,} trades/yr "
                  f"({total_n/252:.0f}/day), "
                  f"~{fmt_d(total_dollars)}\n")

    p = OUT / "report_be_plus_cat_stop.md"
    p.write_text("\n".join(L), encoding="utf-8")
    return p


def main():
    t0 = time.time()
    print(f"Loading {SOURCE}...")
    trades = pd.read_csv(SOURCE)
    print(f"  {len(trades):,} trades")
    print("Reloading bars...")
    bars_1s = load_v0_1s(V0_PARQUET)
    bars_1m = resample_1s_to_1m(bars_1s)
    bars_1m = annotate_sessions_ct(bars_1m)
    print(f"  {len(bars_1m):,} 1m bars")

    n_combos = len(CAT_STOP_PTS) * len(BE_THRESHOLDS_PTS)
    print(f"\nGrid: {n_combos} (cat_stop, be) combos × "
          f"{len(trades):,} trades")

    grid_overall_rows = []
    grid_per_cell_rows = []
    for cat in CAT_STOP_PTS:
        for be in BE_THRESHOLDS_PTS:
            t1 = time.time()
            resim = resimulate_be_plus_cat(
                trades, bars_1m, cat, be)
            elapsed = time.time() - t1
            s = stats(resim)
            s["cat_stop_pts"] = cat
            s["be_threshold"] = be
            grid_overall_rows.append(s)
            print(f"  cat={cat:>5}  be={be:>4}  "
                  f"WR={s['win_rate']:.1%}  "
                  f"BE%={s['be_stop_rate']:.1%}  "
                  f"cat%={s['cat_loss_rate']:.1%}  "
                  f"PnL={s['mean_pnl']:+.3f}  "
                  f"({elapsed:.1f}s)")
            # Per-cell
            for keys, g in resim.groupby(
                    ["level_pair", "entry_session"],
                    observed=True):
                cs = stats(g)
                cs["level_pair"] = keys[0]
                cs["entry_session"] = keys[1]
                cs["cat_stop_pts"] = cat
                cs["be_threshold"] = be
                grid_per_cell_rows.append(cs)

    grid_overall = pd.DataFrame(grid_overall_rows)
    grid_per_cell = pd.DataFrame(grid_per_cell_rows)
    grid_overall.to_csv(
        OUT / "be_cat_grid_overall.csv", index=False)
    grid_per_cell.to_csv(
        OUT / "be_cat_grid_per_cell.csv", index=False)

    # Best per cell
    best_rows = []
    for keys, g in grid_per_cell.groupby(
            ["level_pair", "entry_session"], observed=True):
        best = g.loc[g["mean_pnl"].idxmax()]
        best_rows.append({
            "level_pair": keys[0],
            "entry_session": keys[1],
            "n": int(best["n"]),
            "best_cat": float(best["cat_stop_pts"]),
            "best_be": float(best["be_threshold"]),
            "best_win_rate": float(best["win_rate"]),
            "best_be_stop_rate": float(best["be_stop_rate"]),
            "best_cat_loss_rate": float(best["cat_loss_rate"]),
            "best_mean_pnl": float(best["mean_pnl"]),
            "best_total_pnl": float(best["total_pnl"]),
            "best_annual_dollars": float(best["annual_dollars"]),
        })
    best_per_cell = pd.DataFrame(best_rows)
    best_per_cell.to_csv(OUT / "be_cat_best_per_cell.csv",
                                 index=False)

    print("\nWriting report...")
    rp = write_report(grid_overall, best_per_cell,
                            grid_per_cell, n_combos)
    print(f"Report: {rp}")
    print(f"Total elapsed: {(time.time() - t0)/60:.1f} min")
    return 0


if __name__ == "__main__":
    sys.exit(main())
