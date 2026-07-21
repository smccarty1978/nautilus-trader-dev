"""Re-breach rescue analysis.

Two parts:

PART 1 — Deep-win second-leg MAE
  For winners with deep MAE AND no first-bar follow-through, walk
  bars from first-bar close forward and measure MAE relative to
  first_bar_close. This shows how far the trade had to go in our
  unfavored direction AFTER the first bar failed before eventually
  recovering to target.

PART 2 — "Stop early + take next breach" simulation
  For each trade, sweep early-stop distances X in {5, 7.5, 10, 15}.
  If the trade's MAE >= X (would have stopped at X):
    - Replace original outcome with -X loss
    - Search for next same-direction same-level Goldilocks trigger
      within REENTRY_WINDOW_BARS bars after the stop
    - If found: add that re-trade's outcome (using the SAME early-
      stop rule recursively for fairness)
    - If not found: just take the -X loss
  Compare combined PnL vs original strategy.

This tests the user's hypothesis: "riding a trade 20+pts adverse
for a 22.5pt target is bad R/R; better to take the small loss and
re-enter on the next breach."
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

DEEP_MAE_WIDE = 15.0
DEEP_MAE_NARROW = 12.0
WIDE_GAP_THRESHOLD = 25.0
EARLY_STOP_PTS_LIST = [5.0, 7.5, 10.0, 15.0]
REENTRY_WINDOW_BARS = 60       # how long to wait for re-breach
COMMISSION_PTS = 0.25
NQ_DOLLAR_PER_PT = 20.0
MAX_BARS = 120


def deep_mae_threshold_for(gap):
    return DEEP_MAE_WIDE if gap >= WIDE_GAP_THRESHOLD else DEEP_MAE_NARROW


# -------- PART 1: deep-win second-leg MAE --------

def deep_win_second_leg(trades, bars_1m):
    """For deep_wins with first_bar_winner==0, compute MAE measured
    from first_bar_close until target hit."""
    bars = bars_1m.reset_index(drop=False)
    highs = bars["high"].values
    lows = bars["low"].values
    n_bars = len(bars)

    # Identify subset
    gap = trades["next_level"] - trades["breach_level"]
    threshold = np.where(gap >= WIDE_GAP_THRESHOLD,
                              DEEP_MAE_WIDE, DEEP_MAE_NARROW)
    subset_mask = (
        (trades["outcome"] == "win") &
        (trades["mae_pts"] > threshold) &
        (trades["first_bar_winner"] == 0)
    )
    subset = trades[subset_mask].copy().reset_index(drop=True)
    if len(subset) == 0:
        return subset

    print(f"  deep wins with no first-bar follow-through: "
          f"{len(subset):,}")

    eidx = subset["entry_idx"].astype(int).values
    xidx = subset["exit_idx"].astype(int).values
    d = subset["direction"].astype(int).values
    fbc = subset["first_bar_close"].astype(float).values

    second_leg_mae = np.zeros(len(subset))
    for i in range(len(subset)):
        # Start from bar AFTER first bar
        # (entry_idx is first bar; entry_idx+1 is next)
        start = eidx[i] + 1
        end = min(xidx[i], n_bars - 1)
        if start > end:
            continue
        max_adv = 0.0
        di = d[i]
        ref = fbc[i]
        for k in range(start, end + 1):
            h = highs[k]; l = lows[k]
            if di == 1:
                adv = ref - l
            else:
                adv = h - ref
            if adv > max_adv:
                max_adv = adv
        second_leg_mae[i] = max_adv

    subset["second_leg_mae_pts"] = second_leg_mae
    subset["entry_to_fb_close_pts"] = (
        subset["first_bar_close"] - subset["entry_price"]
    ) * subset["direction"]
    return subset


# -------- PART 2: Re-breach simulation --------

def find_next_rebreach(t, trades_sorted, exit_idx_after,
                              max_window):
    """Find earliest same-direction same-level Goldilocks trigger
    that occurred AFTER exit_idx_after, within max_window bars.
    Returns None if no re-breach available."""
    cand = trades_sorted[
        (trades_sorted["entry_idx"] > exit_idx_after) &
        (trades_sorted["entry_idx"] <= (
            exit_idx_after + max_window)) &
        (trades_sorted["breach_level"] == t["breach_level"]) &
        (trades_sorted["direction"] == t["direction"])
    ]
    if len(cand) == 0:
        return None
    return cand.iloc[0]


def simulate_early_stop_with_reentry(trades, early_stop_pts,
                                                max_chain=3):
    """For each trade, apply early-stop rule and recursively try
    to re-enter on next same-level breach.

    Returns DataFrame with combined_pnl_net per trade (sum of
    initial trade + chained re-trades).
    """
    trades_sorted = trades.sort_values("entry_idx").copy()
    out = trades.copy().reset_index(drop=True)

    # We need a fast way to find "next breach" — index by
    # (level, direction)
    grouped = {}
    for keys, g in trades_sorted.groupby(
            ["breach_level", "direction"], observed=True):
        grouped[keys] = g.sort_values("entry_idx")

    combined_pnl_gross = np.zeros(len(out))
    n_chain = np.zeros(len(out), dtype=int)

    for i in range(len(out)):
        t = out.iloc[i]
        gap = t["next_level"] - t["breach_level"]
        # Did THIS trade trigger the early stop? (mae_pts >= X)
        chain_pnl = 0.0
        chain_count = 0
        cur = t.copy()
        cur_exit_idx = int(t["exit_idx"])  # original exit
        for _ in range(max_chain):
            chain_count += 1
            if cur["mae_pts"] >= early_stop_pts:
                # Stopped at early stop
                chain_pnl += -early_stop_pts
                # Find next re-breach
                key = (cur["breach_level"],
                          int(cur["direction"]))
                pool = grouped.get(key)
                if pool is None:
                    break
                # MAE was reached SOMEWHERE between entry_idx and
                # exit_idx. We don't know exactly when. Approximate:
                # use entry_idx + 1 as the earliest possible stop
                # bar (conservative — we may have stopped in bar 1).
                # For simplicity use original exit_idx as the
                # "stop bar" — we wait until original exit then
                # look for re-breach.
                stop_bar = cur_exit_idx
                next_t = find_next_rebreach(
                    cur, pool, stop_bar, REENTRY_WINDOW_BARS)
                if next_t is None:
                    break
                cur = next_t
                cur_exit_idx = int(next_t["exit_idx"])
                continue
            else:
                # Trade didn't hit early stop — use its actual PnL
                chain_pnl += float(cur["pnl_pts"])
                break
        combined_pnl_gross[i] = chain_pnl
        n_chain[i] = chain_count

    out[f"combined_pnl_gross_X{early_stop_pts}"] = combined_pnl_gross
    out[f"combined_pnl_net_X{early_stop_pts}"] = (
        combined_pnl_gross - COMMISSION_PTS * n_chain)
    out[f"n_chain_X{early_stop_pts}"] = n_chain
    return out


def stats_per_cell(df, pnl_col, group_cols):
    rows = []
    for keys, g in df.groupby(group_cols, observed=True):
        if not isinstance(keys, tuple): keys = (keys,)
        n = len(g)
        rows.append({
            **dict(zip(group_cols, keys)),
            "n": n,
            "mean_pnl": float(g[pnl_col].mean()),
            "total_pnl": float(g[pnl_col].sum()),
            "annual_dollars": float(
                g[pnl_col].sum() * NQ_DOLLAR_PER_PT),
        })
    return pd.DataFrame(rows)


def fmt_p(v):
    if v is None or pd.isna(v): return "—"
    return f"{100*v:.1f}%"


def fmt_f(v, dp=2):
    if v is None or pd.isna(v): return "—"
    return f"{v:+.{dp}f}"


def fmt_d(v):
    if v is None or pd.isna(v): return "—"
    return f"${v:,.0f}"


def write_report(deep_subset, sweep_overall, sweep_per_cell,
                       orig_per_cell):
    L = []
    L.append("# Re-Breach Rescue Analysis "
              "— Level Momentum\n")

    L.append("## Part 1 — Deep-win second-leg MAE\n")
    L.append("Subset: winners with deep MAE (>15 pt for wide "
              "gaps, >12 pt for narrow) AND first bar closed "
              "ADVERSELY (no first-bar follow-through).\n")
    if len(deep_subset) == 0:
        L.append("No qualifying trades.\n")
    else:
        n = len(deep_subset)
        s2l = deep_subset["second_leg_mae_pts"]
        L.append(f"- n = {n:,}")
        L.append(f"- Second-leg MAE (from first-bar close):")
        L.append(f"  - p50 = {np.percentile(s2l, 50):.2f} pts")
        L.append(f"  - p75 = {np.percentile(s2l, 75):.2f} pts")
        L.append(f"  - p90 = {np.percentile(s2l, 90):.2f} pts")
        L.append(f"  - p95 = {np.percentile(s2l, 95):.2f} pts")
        L.append(f"  - mean = {s2l.mean():.2f} pts")
        L.append(f"- For comparison, distance from entry to "
                  "first-bar close (where the failure happened):")
        ent_dist = deep_subset["entry_to_fb_close_pts"]
        L.append(f"  - mean = {ent_dist.mean():.2f} pts "
                  "(negative = adverse)")
        L.append("")
        L.append("**Interpretation**: these wins didn't just "
                  "draw down a little — they drew down "
                  f"{s2l.mean():.0f} pts on average AFTER the "
                  "first bar already showed adverse movement. The "
                  "second leg is a real adverse phase before the "
                  "eventual recovery.\n")

    L.append("## Part 2 — Stop early + re-enter on next breach\n")
    L.append(f"Rule: if MAE >= X, stop out at -X pts. Then look "
              f"for next same-direction same-level Goldilocks "
              f"trigger within {REENTRY_WINDOW_BARS} bars. "
              "Recursively apply same rule (max 3 chains).\n\n"
              f"Commission: {COMMISSION_PTS} pts per trade in "
              "chain.\n")

    L.append("### Overall comparison (all trades)\n")
    L.append("| Strategy | Mean PnL net | Total | Annual $ |")
    L.append("|---|--:|--:|--:|")
    orig_mean = float(
        (sweep_overall["pnl_pts"] - COMMISSION_PTS).mean())
    orig_tot = float(sweep_overall["pnl_pts"].sum()
                          - COMMISSION_PTS * len(sweep_overall))
    L.append(f"| Original (no early stop) | "
              f"{fmt_f(orig_mean, 3)} | "
              f"{fmt_f(orig_tot, 0)} | "
              f"{fmt_d(orig_tot * NQ_DOLLAR_PER_PT)} |")
    for X in EARLY_STOP_PTS_LIST:
        col = f"combined_pnl_net_X{X}"
        if col not in sweep_overall.columns: continue
        m = float(sweep_overall[col].mean())
        t = float(sweep_overall[col].sum())
        L.append(
            f"| Early-stop @{X} pt + re-enter | "
            f"{fmt_f(m, 3)} | {fmt_f(t, 0)} | "
            f"{fmt_d(t * NQ_DOLLAR_PER_PT)} |")
    L.append("")

    L.append("### Per (pair × session) — best early-stop "
              "X for chain strategy\n")
    # For each cell, find best X
    L.append("| Pair | Session | n | Orig Net | Best X | "
             "Chain Net | Δ vs Orig | Annual $ |")
    L.append("|---|---|--:|--:|--:|--:|--:|--:|")
    cells = sweep_overall[
        ["level_pair", "entry_session"]].drop_duplicates()
    rows = []
    for _, c in cells.iterrows():
        sub = sweep_overall[
            (sweep_overall["level_pair"] == c["level_pair"]) &
            (sweep_overall["entry_session"]
                == c["entry_session"])]
        n = len(sub)
        if n < 500: continue
        orig_m = float(
            (sub["pnl_pts"] - COMMISSION_PTS).mean())
        best_X = None
        best_m = -1e9
        best_total = 0.0
        for X in EARLY_STOP_PTS_LIST:
            col = f"combined_pnl_net_X{X}"
            if col not in sub.columns: continue
            m = float(sub[col].mean())
            if m > best_m:
                best_m = m
                best_X = X
                best_total = float(sub[col].sum())
        rows.append({
            "level_pair": c["level_pair"],
            "entry_session": c["entry_session"],
            "n": n,
            "orig_mean": orig_m,
            "best_X": best_X,
            "chain_mean": best_m,
            "delta": best_m - orig_m,
            "annual": best_total * NQ_DOLLAR_PER_PT,
        })
    rows_df = pd.DataFrame(rows).sort_values(
        "delta", ascending=False)
    for _, r in rows_df.iterrows():
        L.append(
            f"| {r['level_pair']} | {r['entry_session']} | "
            f"{int(r['n']):,} | {fmt_f(r['orig_mean'], 3)} | "
            f"{r['best_X']:.1f} | {fmt_f(r['chain_mean'], 3)} | "
            f"{fmt_f(r['delta'], 3)} | "
            f"{fmt_d(r['annual'])} |")
    L.append("")

    p = OUT / "report_rebreach_rescue.md"
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

    print("\nPart 1 — deep-win second-leg MAE...")
    deep_subset = deep_win_second_leg(trades, bars_1m)
    if len(deep_subset):
        deep_subset.to_csv(
            OUT / "deep_win_no_fb_followthru.csv",
            index=False)
        print(f"  saved {len(deep_subset):,} trades")
        s2l = deep_subset["second_leg_mae_pts"]
        print(f"  second-leg MAE: mean {s2l.mean():.2f}, "
              f"p50 {np.percentile(s2l, 50):.2f}, "
              f"p90 {np.percentile(s2l, 90):.2f}")

    print("\nPart 2 — early-stop + re-entry simulation...")
    sweep = trades.copy()
    for X in EARLY_STOP_PTS_LIST:
        t1 = time.time()
        print(f"  early-stop X = {X}...")
        sweep = simulate_early_stop_with_reentry(sweep, X)
        col = f"combined_pnl_net_X{X}"
        m = float(sweep[col].mean())
        tot = float(sweep[col].sum())
        chain_avg = float(sweep[f"n_chain_X{X}"].mean())
        print(f"    mean PnL net = {m:+.3f}, "
              f"total = {tot:+.0f}, "
              f"avg chain length = {chain_avg:.2f}, "
              f"({time.time()-t1:.1f}s)")
    sweep.to_csv(OUT / "rebreach_sweep_per_trade.csv",
                       index=False)

    print("\nWriting report...")
    rp = write_report(deep_subset, sweep, None, None)
    print(f"Report: {rp}")
    print(f"Total elapsed: {(time.time() - t0)/60:.1f} min")
    return 0


if __name__ == "__main__":
    sys.exit(main())
