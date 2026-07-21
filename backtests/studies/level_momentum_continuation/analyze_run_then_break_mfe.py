"""For 'run-then-break' BE-stop trades (clean armers that
reverse), what was max MFE before the trade gave it back?

Population: no-cat + BE=2.5 (best deployment cell).
Run-then-break = trade where the arm (+2.5 MFE) was hit BEFORE
any meaningful MAE — i.e., trade ran clean to +2.5+ then reversed.

Question: of run-then-break trades that BE-stop (don't reach
target), what's the distribution of their peak MFE? This sizes
the partial-profit opportunity if we exited some/all at e.g.
+5, +7.5, +10 pts.
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
    simulate_trade_1s, NO_CAT_SENTINEL,
    BE_STOP_OFFSET_TICKS, TICK_SIZE,
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

        rows = []
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

            xi = min(int(r["exit_idx_global"]),
                          len(highs_1s) - 1)
            sli_h = highs_1s[e1s : xi + 1]
            sli_l = lows_1s[e1s : xi + 1]
            if di == 1:
                mae_series = entry_px - sli_l
                mfe_series = sli_h - entry_px
            else:
                mae_series = sli_h - entry_px
                mfe_series = entry_px - sli_l

            if len(mae_series) == 0: continue
            max_mae = float(np.max(mae_series))
            max_mae_at = int(np.argmax(mae_series))
            max_mfe = float(np.max(mfe_series))

            # Find arming bar (first time MFE >= 2.5)
            arm_mask = mfe_series >= 2.5
            arm_at = (int(np.argmax(arm_mask))
                            if arm_mask.any() else -1)

            mae_before_arm = (arm_at >= 0
                                       and max_mae_at < arm_at)

            rows.append({
                "outcome": r["outcome"],
                "pnl_net": r["pnl_net"],
                "max_mae": max_mae,
                "max_mae_at": max_mae_at,
                "max_mfe": max_mfe,
                "arm_at": arm_at,
                "mae_before_arm": mae_before_arm,
            })
            last_chain_exit_1s = r["exit_idx_global"]

        df = pd.DataFrame(rows)
        n_total = len(df)

        # Run-then-break: armed AND max MAE happens AT/AFTER arm
        # AND we want the "clean" subset — say, MAE before arm <
        # 0.5 pts (essentially zero adverse before arming)
        armed = df[df["arm_at"] >= 0]
        # Define run-then-break strictly: max_mae_at >= arm_at
        # AND mae before arm < 0.5 pts (truly clean rise)
        # First measure adverse excursion during [0, arm_at)
        # using the slice; need to recompute or approximate.
        # Use mae_before_arm flag inverse as approximation.
        rtb = armed[~armed["mae_before_arm"]]
        n_rtb = len(rtb)
        rtb_win = rtb[rtb["outcome"] == "win"]
        rtb_be = rtb[rtb["outcome"] == "be_stop"]
        rtb_eod = rtb[rtb["outcome"] == "eod_flat"]

        print(f"\n[{year}] no-cat + BE=2.5 population: n={n_total:,}")
        print(f"  Armed: {len(armed):,} "
              f"({100*len(armed)/n_total:.1f}%)")
        print(f"  Run-then-break (clean rise to +2.5+): "
              f"{n_rtb:,} ({100*n_rtb/n_total:.1f}%)")
        if n_rtb > 0:
            print(f"    -> wins (PT hit): {len(rtb_win):,} "
                  f"({100*len(rtb_win)/n_rtb:.1f}%)")
            print(f"    -> BE-stops:      {len(rtb_be):,} "
                  f"({100*len(rtb_be)/n_rtb:.1f}%)")
            print(f"    -> EOD-flat:      {len(rtb_eod):,} "
                  f"({100*len(rtb_eod)/n_rtb:.1f}%)")

        if len(rtb_be) > 0:
            mfe_be = rtb_be["max_mfe"]
            print(
                f"\n[{year}] Run-then-break BE-stops: "
                f"max MFE distribution (n={len(rtb_be):,}):")
            for q in (0.10, 0.25, 0.50, 0.75, 0.90, 0.95, 0.99):
                v = float(np.percentile(mfe_be, 100*q))
                print(f"  p{int(100*q):02d}: {v:6.2f} pts")
            print(f"  mean: {float(mfe_be.mean()):6.2f} pts")
            print(f"  max:  {float(mfe_be.max()):6.2f} pts")

            # What if we took partial profit at fixed MFE?
            print(
                f"\n[{year}] If we exited run-then-break BE-stops "
                f"at fixed MFE target:")
            print("  PT  | # would-fire | % of rtb_be | gross/trade | $/trade ")
            for pt in (3.0, 4.0, 5.0, 7.5, 10.0, 12.5, 15.0,
                              20.0, 25.0):
                fires = (mfe_be >= pt).sum()
                pct = 100 * fires / len(rtb_be)
                # Per-trade in this population: if MFE >= PT,
                # exit at PT; else BE-stop at $0
                gross_per = (
                    fires * pt + (len(rtb_be) - fires) * 0
                ) / len(rtb_be)
                net_per = gross_per - COMMISSION_PTS
                print(
                    f"  {pt:>4} | {fires:>11,} | "
                    f"{pct:>9.1f}% | "
                    f"{gross_per:>+10.3f} | "
                    f"${net_per * NQ_DOLLAR_PER_PT:>+8,.2f}")

        if len(rtb_win) > 0:
            mfe_w = rtb_win["max_mfe"]
            print(
                f"\n[{year}] Run-then-break WINS: "
                f"max MFE distribution (n={len(rtb_win):,}):")
            for q in (0.25, 0.50, 0.75, 0.95):
                v = float(np.percentile(mfe_w, 100*q))
                print(f"  p{int(100*q):02d}: {v:6.2f} pts")


if __name__ == "__main__":
    main()
