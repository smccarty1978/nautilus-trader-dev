"""OOS check: Level-Momentum + BE=2.5 (with ORIGINAL 'one prior in
sequence' stops) on NQ 2024 .v.0 data.

This isolates the first profitable finding (BE rule alone, no Cat
substitution) and validates it on a fresh year.
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


V0_PARQUET = Path("data/raw/NQ_v0_1s_2024.parquet")
OUT = Path(
    "studies/level_momentum_continuation/results_nq_2024_be_only")
OUT.mkdir(parents=True, exist_ok=True)

BE_THRESHOLD_PTS = 2.5
COMMISSION_PTS = 0.25
NQ_DOLLAR_PER_PT = 20.0
MAX_BARS = 120


def simulate_trade_with_be(t, bars, be_threshold,
                                   max_bars=MAX_BARS):
    """Simulate one trade with original stop + BE=X rule.
    Returns dict similar to simulate_trade output but with new
    outcome categories: win, loss, be_stop, timed_out.
    """
    n = len(bars)
    entry_idx = t.bar_idx + 1
    if entry_idx >= n:
        return None

    opens = bars["open"].values
    highs = bars["high"].values
    lows = bars["low"].values
    closes = bars["close"].values
    ts_closes = bars["ts_close"].values
    sessions = bars["session"].values

    entry_price = opens[entry_idx]
    di = t.direction
    target = t.target
    stop = t.stop  # original "one prior in sequence" stop

    last = min(entry_idx + max_bars - 1, n - 1)
    armed = False
    mfe_so_far = 0.0
    outcome = None
    exit_idx = entry_idx
    exit_px = entry_price
    bar_armed = -1

    for i in range(entry_idx, last + 1):
        h = highs[i]; l = lows[i]; c = closes[i]
        # 1. BE stop check
        if armed:
            if di == 1 and l <= entry_price:
                outcome = "be_stop"
                exit_idx = i
                exit_px = entry_price
                break
            if di == -1 and h >= entry_price:
                outcome = "be_stop"
                exit_idx = i
                exit_px = entry_price
                break
        # 2. Original stop
        if di == 1 and l <= stop:
            outcome = "loss"
            exit_idx = i
            exit_px = stop
            break
        if di == -1 and h >= stop:
            outcome = "loss"
            exit_idx = i
            exit_px = stop
            break
        # 3. Target
        if di == 1 and h >= target:
            outcome = "win"
            exit_idx = i
            exit_px = target
            break
        if di == -1 and l <= target:
            outcome = "win"
            exit_idx = i
            exit_px = target
            break
        # 4. Update MFE; arm BE
        bar_mfe = (h - entry_price) if di == 1 else (
            entry_price - l)
        if bar_mfe > mfe_so_far:
            mfe_so_far = bar_mfe
        if not armed and mfe_so_far >= be_threshold:
            armed = True
            bar_armed = i

    if outcome is None:
        outcome = "timed_out"
        exit_idx = last
        exit_px = closes[last]

    pnl_gross = (exit_px - entry_price) * di

    return {
        "trigger_ts_close": pd.Timestamp(t.bar_ts_close),
        "trigger_session": t.bar_session,
        "direction": di,
        "breach_level": t.breach_level,
        "next_level": t.next_level,
        "target": target,
        "stop": stop,
        "close_at_breach": t.close_at_breach,
        "entry_idx": entry_idx,
        "entry_price": entry_price,
        "entry_ts_close": pd.Timestamp(ts_closes[entry_idx]),
        "entry_session": sessions[entry_idx],
        "exit_idx": exit_idx,
        "exit_price": exit_px,
        "exit_ts_close": pd.Timestamp(ts_closes[exit_idx]),
        "bars_held": exit_idx - entry_idx + 1,
        "outcome": outcome,
        "pnl_pts_gross": pnl_gross,
        "pnl_pts_net": pnl_gross - COMMISSION_PTS,
        "be_armed": bool(armed),
        "bar_armed": bar_armed,
    }


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
        "armed_rate": float(g["be_armed"].mean()),
        "mean_pnl_net": float(pnl.mean()),
        "median_pnl_net": float(pnl.median()),
        "total_pnl_net": float(pnl.sum()),
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


def write_report(trades, agg_overall, agg_pair_session,
                       n_filtered_bars, n_total_bars):
    L = []
    L.append("# OOS Validation: BE=2.5 + Original Stops "
              "— NQ 2024\n")
    L.append("## Method\n")
    L.append(
        "Same Goldilocks-filtered Level Momentum strategy as 2025, "
        f"with BE-stop activation at MFE >= {BE_THRESHOLD_PTS} pt "
        "(move stop to entry). NO Cat-stop substitution — uses "
        "the ORIGINAL 'one prior in sequence' stop per pair.\n\n"
        f"Source: NQ.v.0 1s -> 1m. Roll filter (±3d around "
        f"quarterly rolls) dropped {n_filtered_bars:,} of "
        f"{n_total_bars:,} bars.\n\n"
        f"Commission: {COMMISSION_PTS} pts. Multiplier: "
        f"${NQ_DOLLAR_PER_PT}/pt.\n")

    L.append("## Overall (all pairs/sessions, all triggers)\n")
    s = agg_overall
    L.append(f"- n trades = {s['n']:,}")
    L.append(f"- WR: {fmt_p(s['win_rate'])} | "
              f"BE-stop: {fmt_p(s['be_stop_rate'])} | "
              f"Loss: {fmt_p(s['loss_rate'])} | "
              f"TimedOut: {fmt_p(s['timed_out_rate'])}")
    L.append(f"- Armed%: {fmt_p(s['armed_rate'])}")
    L.append(f"- **Mean PnL net: {fmt_f(s['mean_pnl_net'], 3)} pts**")
    L.append(f"- Median: {fmt_f(s['median_pnl_net'], 2)}")
    L.append(f"- Total PnL net: {fmt_f(s['total_pnl_net'], 0)} pts")
    L.append(f"- **Annual $ on NQ: {fmt_d(s['annual_dollars'])}**\n")

    L.append("## Per (pair × session)\n")
    L.append("Sorted by mean PnL net descending.\n")
    L.append("| Pair | Session | n | WR | BE% | Loss% | "
             "Mean Net | Total Net | Annual $ |")
    L.append("|---|---|--:|--:|--:|--:|--:|--:|--:|")
    s_sorted = agg_pair_session.sort_values(
        "mean_pnl_net", ascending=False)
    for _, r in s_sorted.iterrows():
        L.append(
            f"| {r['level_pair']} | {r['entry_session']} | "
            f"{int(r['n']):,} | {fmt_p(r['win_rate'])} | "
            f"{fmt_p(r['be_stop_rate'])} | "
            f"{fmt_p(r['loss_rate'])} | "
            f"{fmt_f(r['mean_pnl_net'], 3)} | "
            f"{fmt_f(r['total_pnl_net'], 0)} | "
            f"{fmt_d(r['annual_dollars'])} |")
    L.append("")

    L.append("## Top deployable cells (mean Net > +$0.30, n >= 1,000)\n")
    cands = agg_pair_session[
        (agg_pair_session["mean_pnl_net"] > 0.30) &
        (agg_pair_session["n"] >= 1000)
    ].sort_values("mean_pnl_net", ascending=False)
    if cands.empty:
        L.append("None.\n")
    else:
        L.append("| Pair | Session | n | WR | Mean Net | "
                 "Annual $ |")
        L.append("|---|---|--:|--:|--:|--:|")
        for _, r in cands.iterrows():
            L.append(
                f"| {r['level_pair']} | {r['entry_session']} | "
                f"{int(r['n']):,} | "
                f"{fmt_p(r['win_rate'])} | "
                f"{fmt_f(r['mean_pnl_net'], 3)} | "
                f"{fmt_d(r['annual_dollars'])} |")
        L.append("")
        total_n = int(cands["n"].sum())
        total_dollars = cands["annual_dollars"].sum()
        L.append(f"**Combined**: {total_n:,} trades/yr "
                  f"({total_n/252:.0f}/day), "
                  f"~{fmt_d(total_dollars)}\n")

    p = OUT / "report_be_only_2024_oos.md"
    p.write_text("\n".join(L), encoding="utf-8")
    return p


def main():
    t0 = time.time()
    print(f"Loading {V0_PARQUET}...")
    bars_1s = load_v0_1s(V0_PARQUET)
    print(f"  loaded {len(bars_1s):,} 1s bars")
    print("Resampling 1s -> 1m...")
    bars_1m = resample_1s_to_1m(bars_1s)
    print(f"  {len(bars_1m):,} 1m bars")
    bars_1m = annotate_sessions_ct(bars_1m)
    n_total = len(bars_1m)

    # Roll filter (±3 days)
    print("Applying roll filter...")
    bars_filt, dropped = filter_roll_window(bars_1m, 3)
    print(f"  dropped {dropped:,}, kept {len(bars_filt):,}")

    # Reset index for trigger detection
    bars_reset = bars_filt.reset_index(drop=False)

    print("Detecting Goldilocks triggers...")
    triggers = detect_triggers(bars_reset)
    print(f"  {len(triggers):,} triggers")

    print(f"Simulating with BE={BE_THRESHOLD_PTS} + original stops...")
    rows = []
    for tr in triggers:
        r = simulate_trade_with_be(
            tr, bars_reset, BE_THRESHOLD_PTS)
        if r is not None:
            rows.append(r)
    trades = pd.DataFrame(rows)
    # Pair label
    trades["close_at_breach"] = trades["close_at_breach"].astype(float)
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
    print(f"  {len(trades):,} trades simulated")

    # Save trades
    trades.to_csv(OUT / "trades_be_only_2024.csv", index=False)

    # Aggregate
    print("Aggregating...")
    agg_overall = stats_block(trades)
    agg_ps_rows = []
    for keys, g in trades.groupby(
            ["level_pair", "entry_session"], observed=True):
        s = stats_block(g)
        s["level_pair"] = keys[0]
        s["entry_session"] = keys[1]
        agg_ps_rows.append(s)
    agg_ps = pd.DataFrame(agg_ps_rows)
    agg_ps.to_csv(OUT / "agg_pair_session.csv", index=False)

    print(f"\nOverall: n={agg_overall['n']:,}, "
          f"WR={agg_overall['win_rate']:.1%}, "
          f"mean PnL net={agg_overall['mean_pnl_net']:+.3f}, "
          f"annual=${agg_overall['annual_dollars']:,.0f}")

    print("\nWriting report...")
    rp = write_report(trades, agg_overall, agg_ps,
                            dropped, n_total)
    print(f"Report: {rp}")
    print(f"Total elapsed: {(time.time() - t0)/60:.1f} min")
    return 0


if __name__ == "__main__":
    sys.exit(main())
