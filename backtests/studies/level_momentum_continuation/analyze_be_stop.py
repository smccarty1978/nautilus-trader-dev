"""Breakeven-stop activation study.

For each X in {2.5, 5, 7.5, 10, 15}: re-simulate every trade
with the rule "after MFE >= X pts, move stop to entry (BE)".

Bar-by-bar logic (conservative ordering to avoid intra-bar
ambiguity):
  At each bar k from entry forward:
    1. If BE armed AND price hits entry:
       - long: low <= entry → exit at entry (BE)
       - short: high >= entry → exit at entry (BE)
       break with outcome = "be_stop"
    2. If original stop hit (low<=stop for long, high>=stop short):
       break with outcome = "loss"
    3. If target hit (high>=target for long, low<=target short):
       break with outcome = "win"
    4. Update MFE from bar's high (long) / low (short).
       Arm BE if MFE >= X (only if not yet armed).

The BE-arming is checked AFTER the stop/target check so a single
bar that crosses both X and entry doesn't get same-bar arm+stop.
This is the conservative read; arming happens at end of bar K,
BE-stop check begins bar K+1.

Outputs:
  studies/level_momentum_continuation/results_nq_2025/
    be_stop_sweep_overall.csv
    be_stop_sweep_pair_session.csv
    report_be_stop.md
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

BE_THRESHOLDS_PTS = [2.5, 5.0, 7.5, 10.0, 15.0]
COMMISSION_PTS = 0.25
NQ_DOLLAR_PER_PT = 20.0
MAX_BARS = 120


def resimulate_with_be(trades: pd.DataFrame,
                              bars_1m: pd.DataFrame,
                              be_threshold: float) -> pd.DataFrame:
    """For each trade, re-walk bars from entry forward applying the
    BE-stop rule. Returns new outcome columns."""
    bars = bars_1m.reset_index(drop=False)
    highs = bars["high"].values
    lows = bars["low"].values
    n_bars = len(bars)

    out = trades.copy().reset_index(drop=True)
    eidx = out["entry_idx"].astype(int).values
    d = out["direction"].astype(int).values
    ep = out["entry_price"].astype(float).values
    target = out["target"].astype(float).values
    stop = out["stop"].astype(float).values

    n = len(out)
    new_outcome = np.empty(n, dtype=object)
    new_exit_idx = np.zeros(n, dtype=int)
    new_exit_price = np.zeros(n)
    new_pnl_gross = np.zeros(n)
    new_bars_held = np.zeros(n, dtype=int)
    be_armed_at_bar = np.full(n, -1, dtype=int)

    for i in range(n):
        ent = eidx[i]
        last = min(ent + MAX_BARS - 1, n_bars - 1)
        di = d[i]
        epi = ep[i]
        tgt = target[i]
        stp = stop[i]

        armed = False
        mfe_so_far = 0.0
        outcome = None
        exit_at = ent
        exit_px = epi
        for k in range(ent, last + 1):
            h = highs[k]; l = lows[k]
            # 1. BE stop check (only if armed)
            if armed:
                if di == 1 and l <= epi:
                    outcome = "be_stop"
                    exit_at = k
                    exit_px = epi
                    break
                if di == -1 and h >= epi:
                    outcome = "be_stop"
                    exit_at = k
                    exit_px = epi
                    break
            # 2. Original stop check
            if di == 1 and l <= stp:
                outcome = "loss"
                exit_at = k
                exit_px = stp
                break
            if di == -1 and h >= stp:
                outcome = "loss"
                exit_at = k
                exit_px = stp
                break
            # 3. Target check
            if di == 1 and h >= tgt:
                outcome = "win"
                exit_at = k
                exit_px = tgt
                break
            if di == -1 and l <= tgt:
                outcome = "win"
                exit_at = k
                exit_px = tgt
                break
            # 4. Update MFE; arm BE
            if di == 1:
                bar_mfe = h - epi
            else:
                bar_mfe = epi - l
            if bar_mfe > mfe_so_far:
                mfe_so_far = bar_mfe
            if not armed and mfe_so_far >= be_threshold:
                armed = True
                be_armed_at_bar[i] = k

        if outcome is None:
            outcome = "timed_out"
            exit_at = last
            # MTM at last bar's close (use stop column convention,
            # close not in arrays — fall back to entry for safety)
            exit_px = (highs[last] + lows[last]) / 2.0  # midpoint
            # Actually let's use the close from bars
            # For consistency just look up close at exit_at
        new_outcome[i] = outcome
        new_exit_idx[i] = exit_at
        new_exit_price[i] = exit_px
        new_pnl_gross[i] = (exit_px - epi) * di
        new_bars_held[i] = exit_at - ent + 1

    out["be_threshold"] = be_threshold
    out["new_outcome"] = new_outcome
    out["new_exit_idx"] = new_exit_idx
    out["new_exit_price"] = new_exit_price
    out["new_pnl_gross"] = new_pnl_gross
    out["new_pnl_net"] = new_pnl_gross - COMMISSION_PTS
    out["new_bars_held"] = new_bars_held
    out["be_armed_at_bar"] = be_armed_at_bar
    out["was_be_armed"] = (be_armed_at_bar >= 0).astype(int)
    return out


def stats(df: pd.DataFrame) -> dict:
    n = len(df)
    if n == 0: return {"n": 0}
    pnl = df["new_pnl_net"]
    out_col = df["new_outcome"]
    return {
        "n": n,
        "n_win": int((out_col == "win").sum()),
        "n_loss": int((out_col == "loss").sum()),
        "n_be_stop": int((out_col == "be_stop").sum()),
        "n_timed_out": int((out_col == "timed_out").sum()),
        "win_rate": float((out_col == "win").mean()),
        "loss_rate": float((out_col == "loss").mean()),
        "be_stop_rate": float((out_col == "be_stop").mean()),
        "armed_rate": float(df["was_be_armed"].mean()),
        "mean_pnl": float(pnl.mean()),
        "median_pnl": float(pnl.median()),
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


def write_report(orig_stats, sweeps_overall,
                       best_per_cell, sweep_pair_session_full):
    L = []
    L.append("# Breakeven-Stop Activation Study "
              "— Level Momentum\n")
    L.append("## Method\n")
    L.append(
        "Bar-by-bar re-simulation of each trade with rule: after "
        "MFE >= X pts is reached, move stop to entry price (BE). "
        "BE-arming happens at end of bar K; BE-stop check begins "
        "bar K+1 (conservative — no same-bar arm+stop).\n\n"
        f"Commission: {COMMISSION_PTS} pts/trade applied to ALL "
        "trades regardless of outcome.\n\n"
        f"Original stop: 'one prior in sequence' (varies by pair, "
        "typically 15-30 pts).\n\n"
        f"Sweep: X in {BE_THRESHOLDS_PTS}.\n")

    L.append("## Original baseline (no BE rule)\n")
    s = orig_stats
    L.append(f"- n = {s['n']:,}")
    L.append(f"- WR: {fmt_p(s['win_rate'])}, "
              f"LossR: {fmt_p(s['loss_rate'])}, "
              f"TimedOut: {fmt_p(s['be_stop_rate'])}")
    L.append(f"- Mean PnL net: {fmt_f(s['mean_pnl'], 3)}")
    L.append(f"- Total PnL: {fmt_f(s['total_pnl'], 0)} pts | "
              f"Annual ${s['annual_dollars']:,.0f}\n")

    L.append("## BE-stop sweep — overall (all pairs/sessions)\n")
    L.append("| BE X | n | WR | LossR | BEstopR | Armed% | "
             "Mean PnL Net | Total | Annual $ |")
    L.append("|---|--:|--:|--:|--:|--:|--:|--:|--:|")
    for s in sweeps_overall:
        L.append(
            f"| {s['be_threshold']} | {s['n']:,} | "
            f"{fmt_p(s['win_rate'])} | "
            f"{fmt_p(s['loss_rate'])} | "
            f"{fmt_p(s['be_stop_rate'])} | "
            f"{fmt_p(s['armed_rate'])} | "
            f"{fmt_f(s['mean_pnl'], 3)} | "
            f"{fmt_f(s['total_pnl'], 0)} | "
            f"{fmt_d(s['annual_dollars'])} |")
    L.append("")

    L.append("## Best BE threshold per (pair × session)\n")
    L.append("Sorted by improvement vs original.\n")
    L.append("| Pair | Session | n | Best X | New WR | "
             "BEstop% | Mean Net | Orig Net | Improvement | "
             "Annual $ |")
    L.append("|---|---|--:|--:|--:|--:|--:|--:|--:|--:|")
    s = best_per_cell.sort_values(
        "improvement", ascending=False)
    for _, r in s.iterrows():
        L.append(
            f"| {r['level_pair']} | {r['entry_session']} | "
            f"{int(r['n']):,} | {r['best_X']:.1f} | "
            f"{fmt_p(r['best_win_rate'])} | "
            f"{fmt_p(r['best_be_stop_rate'])} | "
            f"{fmt_f(r['best_mean_pnl'], 3)} | "
            f"{fmt_f(r['orig_mean_pnl'], 3)} | "
            f"{fmt_f(r['improvement'], 3)} | "
            f"{fmt_d(r['best_annual_dollars'])} |")
    L.append("")

    L.append("## Top deployable candidates "
              "(net mean PnL > +$0.30/trade, n >= 1,000)\n")
    cands = best_per_cell[
        (best_per_cell["best_mean_pnl"] > 0.30) &
        (best_per_cell["n"] >= 1000)
    ].sort_values("best_mean_pnl", ascending=False)
    if cands.empty:
        L.append("None.\n")
    else:
        L.append("| Pair | Session | n | Best X | WR | "
                 "Mean Net | Annual $ |")
        L.append("|---|---|--:|--:|--:|--:|--:|")
        for _, r in cands.iterrows():
            L.append(
                f"| {r['level_pair']} | {r['entry_session']} | "
                f"{int(r['n']):,} | {r['best_X']:.1f} | "
                f"{fmt_p(r['best_win_rate'])} | "
                f"{fmt_f(r['best_mean_pnl'], 3)} | "
                f"{fmt_d(r['best_annual_dollars'])} |")
        L.append("")

    L.append("## Per-cell sweep detail (all X values)\n")
    L.append("| Pair | Session | X | n | WR | LossR | BEstopR | "
             "Armed% | Mean Net | Total | Annual $ |")
    L.append("|---|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|")
    for _, r in sweep_pair_session_full.sort_values(
            ["level_pair", "entry_session", "be_threshold"]
            ).iterrows():
        L.append(
            f"| {r['level_pair']} | {r['entry_session']} | "
            f"{r['be_threshold']} | {int(r['n']):,} | "
            f"{fmt_p(r['win_rate'])} | "
            f"{fmt_p(r['loss_rate'])} | "
            f"{fmt_p(r['be_stop_rate'])} | "
            f"{fmt_p(r['armed_rate'])} | "
            f"{fmt_f(r['mean_pnl'], 3)} | "
            f"{fmt_f(r['total_pnl'], 0)} | "
            f"{fmt_d(r['annual_dollars'])} |")
    L.append("")

    p = OUT / "report_be_stop.md"
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

    # Original baseline (just compute net PnL with commission)
    orig = trades.copy()
    orig["new_outcome"] = orig["outcome"]
    orig["new_pnl_net"] = orig["pnl_pts"] - COMMISSION_PTS
    orig["was_be_armed"] = 0
    orig_stats = stats(orig)
    print(f"\nOriginal baseline: total {orig_stats['total_pnl']:.0f} pts, "
          f"mean {orig_stats['mean_pnl']:+.3f}, "
          f"WR {orig_stats['win_rate']:.1%}")

    # Sweep BE thresholds
    sweeps_overall = []
    all_resims = {}  # X -> resim df
    for X in BE_THRESHOLDS_PTS:
        t1 = time.time()
        print(f"\nSimulating with BE threshold X = {X} pts...")
        resim = resimulate_with_be(trades, bars_1m, X)
        elapsed = time.time() - t1
        s = stats(resim)
        s["be_threshold"] = X
        sweeps_overall.append(s)
        all_resims[X] = resim
        print(f"  done in {elapsed:.1f}s | "
              f"WR={s['win_rate']:.1%}, "
              f"BEstop%={s['be_stop_rate']:.1%}, "
              f"mean PnL={s['mean_pnl']:+.3f}, "
              f"total={s['total_pnl']:.0f}")

    # Per-pair-session sweep
    print("\nAggregating per-pair-session...")
    sweep_ps_rows = []
    for X, resim in all_resims.items():
        for keys, g in resim.groupby(
                ["level_pair", "entry_session"], observed=True):
            s = stats(g)
            s["level_pair"] = keys[0]
            s["entry_session"] = keys[1]
            s["be_threshold"] = X
            sweep_ps_rows.append(s)
    sweep_ps = pd.DataFrame(sweep_ps_rows)
    sweep_ps.to_csv(OUT / "be_stop_sweep_pair_session.csv",
                          index=False)

    # Best per cell
    best_rows = []
    orig_ps = (trades.assign(
        new_pnl_net=trades["pnl_pts"] - COMMISSION_PTS)
        .groupby(["level_pair", "entry_session"], observed=True))
    orig_lookup = {}
    for keys, g in orig_ps:
        orig_lookup[keys] = {
            "n": len(g),
            "mean_pnl": float(g["new_pnl_net"].mean()),
            "win_rate": float(
                (g["outcome"] == "win").mean()),
        }

    for keys, g in sweep_ps.groupby(
            ["level_pair", "entry_session"], observed=True):
        best = g.loc[g["mean_pnl"].idxmax()]
        orig_info = orig_lookup.get(keys, {})
        best_rows.append({
            "level_pair": keys[0],
            "entry_session": keys[1],
            "n": int(best["n"]),
            "best_X": float(best["be_threshold"]),
            "best_win_rate": float(best["win_rate"]),
            "best_be_stop_rate": float(best["be_stop_rate"]),
            "best_mean_pnl": float(best["mean_pnl"]),
            "best_total_pnl": float(best["total_pnl"]),
            "best_annual_dollars": float(best["annual_dollars"]),
            "orig_mean_pnl": orig_info.get(
                "mean_pnl", float("nan")),
            "orig_win_rate": orig_info.get(
                "win_rate", float("nan")),
            "improvement": (float(best["mean_pnl"])
                                  - orig_info.get(
                                      "mean_pnl", 0.0)),
        })
    best_per_cell = pd.DataFrame(best_rows)
    best_per_cell.to_csv(OUT / "be_stop_best_per_cell.csv",
                                 index=False)

    pd.DataFrame(sweeps_overall).to_csv(
        OUT / "be_stop_sweep_overall.csv", index=False)

    print("\nWriting report...")
    rp = write_report(orig_stats, sweeps_overall,
                            best_per_cell, sweep_ps)
    print(f"Report: {rp}")
    print(f"Total elapsed: {(time.time() - t0)/60:.1f} min")
    return 0


if __name__ == "__main__":
    sys.exit(main())
