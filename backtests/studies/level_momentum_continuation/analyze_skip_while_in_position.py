"""Position-managed re-aggregation: 'skip while in position'.

Takes the BE=2.5 trade simulation output and applies the rule:
  If a new trigger fires while a prior trade is still open
  (entry_idx <= prior trade's exit_idx), SKIP that trigger.

Reports:
  - Kept trade count vs trigger count (capacity utilization)
  - Aggregate PnL net under single-position management
  - Per-cell breakdown
  - Side-by-side comparison vs the unfiltered (multi-position) view

Runs for both 2024 (OOS) and 2025 (IS) using BE=2.5 + original
"one prior in sequence" stops.
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
    detect_triggers,
)
from studies.level_momentum_continuation.run_nq_2025 import (
    filter_roll_window,
)
from studies.level_momentum_continuation.run_be_only_2024_oos import (
    simulate_trade_with_be, BE_THRESHOLD_PTS,
    COMMISSION_PTS, NQ_DOLLAR_PER_PT, MAX_BARS,
)


OUT = Path(
    "studies/level_momentum_continuation/results_skip_while_open")
OUT.mkdir(parents=True, exist_ok=True)


def simulate_year(year: int) -> pd.DataFrame:
    """Run BE=2.5 + original stops on a year's NQ.v.0 1s data.
    Returns trades DataFrame with entry_idx, exit_idx, pnl_pts_net."""
    parquet = Path(f"data/raw/NQ_v0_1s_{year}.parquet")
    print(f"\n[{year}] loading {parquet}...")
    bars_1s = load_v0_1s(parquet)
    bars_1m = resample_1s_to_1m(bars_1s)
    bars_1m = annotate_sessions_ct(bars_1m)
    n_total = len(bars_1m)
    bars_filt, dropped = filter_roll_window(bars_1m, 3)
    print(f"  bars: {n_total:,} total, {dropped:,} dropped, "
          f"{len(bars_filt):,} kept")

    bars_reset = bars_filt.reset_index(drop=False)
    triggers = detect_triggers(bars_reset)
    print(f"  triggers: {len(triggers):,}")

    rows = []
    for tr in triggers:
        r = simulate_trade_with_be(tr, bars_reset,
                                              BE_THRESHOLD_PTS)
        if r is not None:
            rows.append(r)
    trades = pd.DataFrame(rows)
    L_offset = trades["breach_level"] - (
        (trades["breach_level"] // 100) * 100)
    Y_offset = trades["next_level"] - (
        (trades["next_level"] // 100) * 100)
    Y_offset = Y_offset.where(Y_offset != 100.0, 0.0)
    trades["level_pair"] = (
        L_offset.astype(int).astype(str).str.zfill(2)
        + "->"
        + Y_offset.astype(int).astype(str).str.zfill(2)
        + "_"
        + trades["direction"].map({1: "long", -1: "short"})
    )
    trades["year"] = year
    print(f"  simulated trades: {len(trades):,}")
    return trades


def apply_skip_while_in_position(trades: pd.DataFrame) -> pd.DataFrame:
    """Sort by entry_idx; skip any trigger whose entry_idx <=
    the prior accepted trade's exit_idx."""
    s = trades.sort_values(
        "entry_idx").reset_index(drop=True)
    eidx = s["entry_idx"].values
    xidx = s["exit_idx"].values
    keep_mask = np.zeros(len(s), dtype=bool)
    cur_exit = -1
    for i in range(len(s)):
        if eidx[i] > cur_exit:
            keep_mask[i] = True
            cur_exit = xidx[i]
    return s[keep_mask].copy().reset_index(drop=True)


def stats_block(g: pd.DataFrame) -> dict:
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


def write_report(stats_unfilt, stats_skip,
                       per_cell_unfilt, per_cell_skip):
    L = []
    L.append("# Single-Position Audit "
              "(Skip While In Position)\n")
    L.append("## Method\n")
    L.append(
        "Re-aggregates the BE=2.5 + original-stops simulation "
        "with a single-position rule: any trigger that fires "
        "while a prior trade is still open is SKIPPED.\n\n"
        "Comparison: 'Unfiltered' = original simulation that "
        "treats every trigger as an independent trade (no "
        "position management). 'Skip-while-open' = the realistic "
        "single-position view.\n\n"
        f"Years tested: 2024 (OOS) and 2025 (IS). "
        f"BE threshold = {BE_THRESHOLD_PTS} pt. "
        f"Commission = {COMMISSION_PTS} pt. "
        f"Multiplier = ${NQ_DOLLAR_PER_PT}/pt.\n")

    L.append("## Headline comparison\n")
    L.append("| Year | Mode | Trades | WR | Mean PnL | "
             "Total PnL | Annual $ |")
    L.append("|---|---|--:|--:|--:|--:|--:|")
    for year in [2024, 2025]:
        for mode, s in [
                ("Unfiltered (multi-position)",
                 stats_unfilt[year]),
                ("Skip while open (single-position)",
                 stats_skip[year])]:
            L.append(
                f"| {year} | {mode} | {s['n']:,} | "
                f"{fmt_p(s['win_rate'])} | "
                f"{fmt_f(s['mean_pnl_net'], 3)} | "
                f"{fmt_f(s['total_pnl_net'], 0)} | "
                f"{fmt_d(s['annual_dollars'])} |")
    L.append("")

    L.append("## Capacity utilization\n")
    L.append("| Year | Triggers | Kept (single-pos) | "
             "Capacity % | Trades skipped |")
    L.append("|---|--:|--:|--:|--:|")
    for year in [2024, 2025]:
        u = stats_unfilt[year]["n"]
        k = stats_skip[year]["n"]
        L.append(
            f"| {year} | {u:,} | {k:,} | "
            f"{100*k/u:.1f}% | {u-k:,} |")
    L.append("")

    L.append("## Top deployable cells (skip-while-open mode)\n")
    L.append("Cells with mean PnL net > +$0.30/trade and n >= 200 "
              "in the SKIP-WHILE-OPEN view.\n")
    for year in [2024, 2025]:
        L.append(f"### {year}\n")
        df = per_cell_skip[year]
        cands = df[(df["mean_pnl_net"] > 0.30)
                       & (df["n"] >= 200)
                       ].sort_values("mean_pnl_net",
                                            ascending=False)
        if cands.empty:
            L.append("None.\n")
        else:
            L.append("| Pair | Session | n | WR | Mean Net | "
                     "Annual $ |")
            L.append("|---|---|--:|--:|--:|--:|")
            for _, r in cands.iterrows():
                L.append(
                    f"| {r['level_pair']} | "
                    f"{r['entry_session']} | "
                    f"{int(r['n']):,} | "
                    f"{fmt_p(r['win_rate'])} | "
                    f"{fmt_f(r['mean_pnl_net'], 3)} | "
                    f"{fmt_d(r['annual_dollars'])} |")
            tot_n = int(cands["n"].sum())
            tot_d = float(cands["annual_dollars"].sum())
            L.append(f"\n**Combined (skip-while-open)**: "
                      f"{tot_n:,} trades, {fmt_d(tot_d)}\n")

    L.append("## Per-cell side-by-side (n >= 1,000 in either)\n")
    for year in [2024, 2025]:
        L.append(f"### {year}\n")
        u = per_cell_unfilt[year][["level_pair",
                                              "entry_session", "n",
                                              "mean_pnl_net",
                                              "annual_dollars"]
                                         ].rename(columns={
                                             "n": "n_unf",
                                             "mean_pnl_net":
                                               "mean_unf",
                                             "annual_dollars":
                                               "annual_unf"})
        k = per_cell_skip[year][["level_pair",
                                            "entry_session", "n",
                                            "win_rate",
                                            "mean_pnl_net",
                                            "annual_dollars"]
                                       ].rename(columns={
                                           "n": "n_skip",
                                           "win_rate": "wr_skip",
                                           "mean_pnl_net":
                                             "mean_skip",
                                           "annual_dollars":
                                             "annual_skip"})
        m = u.merge(k, on=["level_pair", "entry_session"],
                       how="outer").fillna(0)
        m["capacity_pct"] = 100 * m["n_skip"] / m["n_unf"].replace(
            0, np.nan)
        m = m.sort_values("annual_skip", ascending=False)
        L.append("| Pair | Session | n_unf | n_skip | Cap% | "
                 "Mean Unf | Mean Skip | Annual Unf | "
                 "Annual Skip |")
        L.append("|---|---|--:|--:|--:|--:|--:|--:|--:|")
        for _, r in m.iterrows():
            if r["n_unf"] < 1000 and r["n_skip"] < 1000: continue
            L.append(
                f"| {r['level_pair']} | "
                f"{r['entry_session']} | "
                f"{int(r['n_unf']):,} | "
                f"{int(r['n_skip']):,} | "
                f"{r['capacity_pct']:.0f}% | "
                f"{fmt_f(r['mean_unf'], 3)} | "
                f"{fmt_f(r['mean_skip'], 3)} | "
                f"{fmt_d(r['annual_unf'])} | "
                f"{fmt_d(r['annual_skip'])} |")
        L.append("")

    p = OUT / "report_skip_while_open.md"
    p.write_text("\n".join(L), encoding="utf-8")
    return p


def main():
    t0 = time.time()
    trades_per_year = {}
    stats_unfilt = {}
    stats_skip = {}
    per_cell_unfilt = {}
    per_cell_skip = {}
    skip_per_year = {}

    for year in [2024, 2025]:
        trades = simulate_year(year)
        trades_per_year[year] = trades

        # Unfiltered stats
        s_unf = stats_block(trades)
        stats_unfilt[year] = s_unf

        # Apply skip-while-in-position
        kept = apply_skip_while_in_position(trades)
        skip_per_year[year] = kept
        s_skip = stats_block(kept)
        stats_skip[year] = s_skip

        print(f"\n[{year}] UNFILTERED: n={s_unf['n']:,}, "
              f"WR={s_unf['win_rate']:.1%}, "
              f"mean={s_unf['mean_pnl_net']:+.3f}, "
              f"annual=${s_unf['annual_dollars']:,.0f}")
        print(f"[{year}] SKIP-WHILE-OPEN: n={s_skip['n']:,} "
              f"({100*s_skip['n']/s_unf['n']:.1f}% capacity), "
              f"WR={s_skip['win_rate']:.1%}, "
              f"mean={s_skip['mean_pnl_net']:+.3f}, "
              f"annual=${s_skip['annual_dollars']:,.0f}")

        # Per-cell aggregations
        per_cell_unfilt[year] = pd.DataFrame([
            {"level_pair": k[0], "entry_session": k[1],
             **stats_block(g)}
            for k, g in trades.groupby(
                ["level_pair", "entry_session"], observed=True)])
        per_cell_skip[year] = pd.DataFrame([
            {"level_pair": k[0], "entry_session": k[1],
             **stats_block(g)}
            for k, g in kept.groupby(
                ["level_pair", "entry_session"], observed=True)])

        # Save trades
        trades.to_csv(
            OUT / f"trades_unfilt_{year}.csv", index=False)
        kept.to_csv(
            OUT / f"trades_skip_{year}.csv", index=False)
        per_cell_unfilt[year].to_csv(
            OUT / f"per_cell_unfilt_{year}.csv", index=False)
        per_cell_skip[year].to_csv(
            OUT / f"per_cell_skip_{year}.csv", index=False)

    print("\nWriting report...")
    rp = write_report(stats_unfilt, stats_skip,
                            per_cell_unfilt, per_cell_skip)
    print(f"Report: {rp}")
    print(f"Total elapsed: {(time.time() - t0)/60:.1f} min")
    return 0


if __name__ == "__main__":
    sys.exit(main())
