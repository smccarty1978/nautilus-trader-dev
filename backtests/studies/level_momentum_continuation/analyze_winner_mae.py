"""For winner trades specifically, what's the MAE distribution?

Direct test: of the trades that actually win (reach next-level
target), what % had MAE > X for each SL candidate?

Rebuilds population from no-cat + BE=2.5 (best cell), tracks
running MAE before exit, then reports:
  - MAE distribution for winners
  - % of winners killed by SL=10, 15, 20, 25, 30
  - $ cost of killed winners (each killed = -SL instead of +25)
"""
from __future__ import annotations
import os, sys
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
from studies.level_momentum_continuation.analyze_sl_be_grid_1s import (
    simulate_trade_1s, NO_CAT_SENTINEL, BE_STOP_OFFSET_TICKS,
    TICK_SIZE,
)

OUT = Path(
    "studies/level_momentum_continuation/results_1s_precision")
NQ_DOLLAR_PER_PT = 20.0
COMMISSION_PTS = 0.25


def main():
    for year in (2024, 2025):
        print(f"\n{'='*70}\n[{year}] loading 1s bars + triggers...")
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

        be_off = BE_STOP_OFFSET_TICKS * TICK_SIZE

        # Run no-cat + BE=2.5 cell. For each trade, compute MAE
        # series before exit so we can ask "what was MAE before
        # the win/loss happened".
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
            sl_px = entry_px - NO_CAT_SENTINEL if di == 1 else (
                entry_px + NO_CAT_SENTINEL)
            be_px = (entry_px + be_off) if di == 1 else (
                entry_px - be_off)
            target = float(tr.target)
            eod_idx = int(next_eod[e1s])
            r = simulate_trade_1s(e1s, di, entry_px, target,
                                           sl_px, be_px, 2.5, eod_idx,
                                           opens_1s, highs_1s,
                                           lows_1s, closes_1s)
            if r is None: continue

            # Compute pre-EXIT MAE
            xi = min(int(r["exit_idx_global"]),
                          len(highs_1s) - 1)
            sli_h = highs_1s[e1s : xi + 1]
            sli_l = lows_1s[e1s : xi + 1]
            if di == 1:
                mae_series = entry_px - sli_l
            else:
                mae_series = sli_h - entry_px
            max_mae = (float(np.max(mae_series))
                              if len(mae_series) else 0.0)

            r["entry_1s_idx"] = e1s
            r["entry_px"] = entry_px
            r["direction"] = di
            r["max_mae_pre_exit"] = max_mae
            chains.append(r)
            last_chain_exit_1s = r["exit_idx_global"]

        df = pd.DataFrame(chains)
        n = len(df)
        winners = df[df["outcome"] == "win"]
        bestops = df[df["outcome"] == "be_stop"]
        eods = df[df["outcome"] == "eod_flat"]
        print(f"\n[{year}] no-cat + BE=2.5 population: n={n:,}")
        print(f"  wins: {len(winners):,} "
              f"({100*len(winners)/n:.1f}%)")
        print(f"  BE-stops: {len(bestops):,} "
              f"({100*len(bestops)/n:.1f}%)")
        print(f"  EOD-flats: {len(eods):,} "
              f"({100*len(eods)/n:.1f}%)")

        # WINNERS' MAE distribution
        mae_w = winners["max_mae_pre_exit"]
        print(f"\n[{year}] WINNERS' max MAE distribution (n={len(winners):,}):")
        for q in (0.25, 0.50, 0.75, 0.90, 0.95, 0.99):
            print(f"  p{int(100*q):02d}: "
                  f"{float(np.percentile(mae_w, 100*q)):6.2f} pts")
        print(f"  max:  {float(mae_w.max()):6.2f} pts")
        print(f"  mean: {float(mae_w.mean()):6.2f} pts")

        # BE-STOP MAE distribution (these dip past entry by
        # construction since BE_offset = +1tick)
        mae_b = bestops["max_mae_pre_exit"]
        print(f"\n[{year}] BE-STOP max MAE distribution "
              f"(n={len(bestops):,}):")
        for q in (0.25, 0.50, 0.75, 0.90, 0.95, 0.99):
            print(f"  p{int(100*q):02d}: "
                  f"{float(np.percentile(mae_b, 100*q)):6.2f} pts")
        print(f"  max:  {float(mae_b.max()):6.2f} pts")

        # SL impact: how many winners would each SL cap have killed?
        print(f"\n[{year}] WINNERS killed by each SL cap:")
        print("  SL  | # winners killed | % winners | $ swing/trade | total $ cost")
        for sl in (5, 7.5, 10, 12.5, 15, 20, 25, 30):
            killed = (mae_w > sl).sum()
            pct = 100 * killed / len(winners)
            # Each killed winner: was +25 (target hit), now -SL
            # Net swing per killed = -(25 + sl) - 0 (was net +25-0.25)
            # Actually: gross was +25, now -sl. Diff = -(25+sl).
            # Net diff (after commission cancels): -(25+sl) pts
            # Approx target distance ~ 25 pts on NQ; use mean win
            mean_win_pts = float(winners["pnl_net"].mean())
            swing_per_kill = -(sl + mean_win_pts + COMMISSION_PTS)
            total_cost = killed * swing_per_kill * NQ_DOLLAR_PER_PT
            print(f"  {sl:>5} | {killed:>15,} | "
                  f"{pct:>7.1f}% | "
                  f"${swing_per_kill * NQ_DOLLAR_PER_PT:>+11,.0f} | "
                  f"${total_cost:>+13,.0f}")

        # BE-stop SAVINGS: how many BE-stops have MAE > SL?
        # Each saved = was 0 net, would now be -SL.
        # NEGATIVE savings (loss conversion).
        print(f"\n[{year}] BE-STOPS converted to losses by each SL cap:")
        print("  SL  | # BE-stops killed | % BE-stops | $ swing/trade | total $ cost")
        for sl in (5, 7.5, 10, 12.5, 15, 20, 25, 30):
            killed = (mae_b > sl).sum()
            pct = 100 * killed / max(len(bestops), 1)
            # was 0 gross 0 net (after BE catch w/ +1tick = 0 net).
            # Now: -sl gross, -sl - 0.25 net.
            # Diff: -(sl + 0.25) - (0) = -(sl+0.25) pts
            swing_per = -(sl + COMMISSION_PTS)
            total_cost = killed * swing_per * NQ_DOLLAR_PER_PT
            print(f"  {sl:>5} | {killed:>16,} | "
                  f"{pct:>9.1f}% | "
                  f"${swing_per * NQ_DOLLAR_PER_PT:>+11,.0f} | "
                  f"${total_cost:>+13,.0f}")

        # Net effect of adding SL cap (winners killed + BE-stops
        # converted to losses + cat-loss savings from never-armed)
        print(f"\n[{year}] NET effect of adding SL cap to no-cat baseline:")
        print("  (assumes no skip-while-open chain shifts)")
        print("  SL  | winners killed cost | BE-stops killed cost | NET")
        baseline_pts = float(df["pnl_net"].sum())
        baseline_dollars = baseline_pts * NQ_DOLLAR_PER_PT
        for sl in (5, 7.5, 10, 12.5, 15, 20, 25, 30):
            kw = (mae_w > sl).sum()
            kb = (mae_b > sl).sum()
            mean_win_pts = float(winners["pnl_net"].mean())
            cost_w = kw * (-(sl + mean_win_pts + COMMISSION_PTS)
                                 ) * NQ_DOLLAR_PER_PT
            cost_b = kb * (-(sl + COMMISSION_PTS)
                                 ) * NQ_DOLLAR_PER_PT
            net = cost_w + cost_b
            print(f"  {sl:>5} | "
                  f"${cost_w:>+13,.0f} ({kw:,}) | "
                  f"${cost_b:>+13,.0f} ({kb:,}) | "
                  f"${net:>+13,.0f}")
        print(f"  Baseline (no-cat, BE=2.5): ${baseline_dollars:,.0f}")
        print(f"  Hypothetical PnL with SL = baseline + NET cost above")

        df.to_csv(
            OUT / f"trades_no_cat_be25_with_mae_{year}.csv",
            index=False)


if __name__ == "__main__":
    main()
