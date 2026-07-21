"""Pandas vs NT 1s reconciliation.

Force the EXACT SAME 1s data through both engines and check if trades match.

Pandas implementation (this script) mirrors NT clean 1-contract design:
  - Source: NQ_v0_1s_2025.parquet (same as NT catalog source)
  - 1m bars: pandas resample(1min, label='right', closed='right') —
    SAME as build_v0_2025_catalog.py used for NT
  - EMA13: ewm(span=13, adjust=False) on 1m close — matches NT EMA
  - Trigger: Goldilocks bullish-bar + EMA13 filter
  - Entry: next 1s bar's OPEN after 1m signal close (1s bar with
    ts_close = signal_ts + 1s)
  - SL: prior-level SL (price-level)
  - PT: full PT (next-level - 2.5)
  - Within-bar fill priority (matching NT BarMatchingEngine default):
    * Bullish bar (close > open): path = open → high → low → close
      → PT fills first if reachable
    * Bearish bar (close < open): path = open → low → high → close
      → SL fills first if reachable
    * Doji (close == open): SL beats PT (conservative)
  - Skip-while-open at 1s precision
  - RTH only (8:30-15:00 CT entries)
  - 1 contract; no v-recovery; no BE
  - Commission $5/contract; no entry slippage; no stop slippage

Then compare trade-by-trade to nt_v0_2025_clean_1s_trades.parquet.

Reconciliation table:
  - same trade count?
  - same signal timestamps?
  - same entries (price, time)?
  - same exits (price, time, reason)?
  - same PnL?
"""
from __future__ import annotations
import os, sys, time
from pathlib import Path
import pandas as pd
import numpy as np
from datetime import time as dt_time
import pytz

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))
os.chdir(project_root)

from studies.level_momentum_continuation.level_study import (
    load_v0_1s, annotate_sessions_ct,
)
from studies.level_momentum_continuation.analyze_breakout_filter import (
    detect_triggers_breakout, assign_group,
)
from studies.level_momentum_continuation.analyze_1s_precision import (
    annotate_sessions_1s, precompute_eod_1s, map_1m_trigger_to_1s_entry,
)

OUT = Path("studies/level_momentum_continuation/results_breakout")
NQ_MULT = 20.0
COMMISSION = 5.0   # dollars per contract round trip
EMA_PERIOD = 13


def sim_1ctr_clean(entry_idx, di, entry_px, target, prior_sl, eod_idx,
                    opens, highs, lows, closes):
    """Walk 1s bars; 1-contract design with prior_SL + full PT.
    Within-bar fill priority: NT-style based on bar shape.
      bullish bar: open → high → low → close (PT fills first if both)
      bearish bar: open → low → high → close (SL fills first if both)
      doji: SL beats PT (conservative)
    No slippage on stops, no commission slippage.
    """
    n = len(highs)
    last = min(eod_idx, n - 1)
    if entry_idx >= n or last < entry_idx:
        return None
    nbars = last - entry_idx + 1
    for s in range(nbars):
        i = entry_idx + s
        o = opens[i]; h = highs[i]; l = lows[i]; c = closes[i]
        if di == 1:
            sl_hit = (l <= prior_sl)
            tgt_hit = (h >= target)
        else:
            sl_hit = (h >= prior_sl)
            tgt_hit = (l <= target)

        if sl_hit and tgt_hit:
            # Both touched in same bar - use bar shape to decide
            if c > o:
                # bullish: high comes first → PT wins
                outcome = "win"; exit_px = float(target)
            elif c < o:
                # bearish: low comes first → SL wins
                outcome = "loss"; exit_px = float(prior_sl)
            else:
                # doji: conservative SL
                outcome = "loss"; exit_px = float(prior_sl)
        elif sl_hit:
            outcome = "loss"; exit_px = float(prior_sl)
        elif tgt_hit:
            outcome = "win"; exit_px = float(target)
        else:
            continue
        # Exit
        pnl_pts = (exit_px - entry_px) * di
        return {
            "outcome": outcome,
            "exit_idx_global": i,
            "exit_px": exit_px,
            "pnl_pts": float(pnl_pts),
        }
    # EOD
    last_close = float(closes[entry_idx + nbars - 1])
    pnl_pts = (last_close - entry_px) * di
    return {
        "outcome": "eod_flat",
        "exit_idx_global": entry_idx + nbars - 1,
        "exit_px": last_close,
        "pnl_pts": float(pnl_pts),
    }


def main():
    t0 = time.time()
    print("=" * 78)
    print("PANDAS vs NT 1s RECONCILIATION (clean 1-contract, NQ.v.0 2025)")
    print("=" * 78)

    print("\n[1] Loading raw 1s data (same source as NT catalog)...")
    bars_1s = load_v0_1s(Path("data/raw/NQ_v0_1s_2025.parquet"))
    bars_1s = annotate_sessions_1s(bars_1s)
    print(f"  {len(bars_1s):,} 1s bars")

    print("\n[2] Resampling to 1m (label=right, closed=right) — same as catalog build...")
    bars_1m = bars_1s[
        ["open", "high", "low", "close", "volume"]
    ].resample("1min", label="right", closed="right").agg({
        "open": "first", "high": "max", "low": "min",
        "close": "last", "volume": "sum",
    }).dropna(subset=["open", "high", "low", "close"])
    bars_1m = annotate_sessions_ct(bars_1m)
    bars_1m["ema13"] = bars_1m["close"].ewm(
        span=EMA_PERIOD, adjust=False).mean()
    print(f"  {len(bars_1m):,} 1m bars")

    print("\n[3] Detecting Goldilocks bullish-bar triggers...")
    triggers = detect_triggers_breakout(bars_1m)
    print(f"  {len(triggers):,} raw triggers")

    print("\n[4] Building chain (skip-while-open, EMA13 filter, RTH only)...")
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
    ema_lookup = pd.Series(
        bars_1m["ema13"].values, index=bars_1m.index)

    last_chain_exit = -1
    rows = []
    for tr in triggers:
        ts = pd.Timestamp(tr["bar_ts_close"])
        if ts.tz is None: ts = ts.tz_localize("UTC")
        else: ts = ts.tz_convert("UTC")
        e = map_1m_trigger_to_1s_entry(ts, ts_close_1s)
        if e < 0: continue
        if e <= last_chain_exit: continue
        if ts not in ema_lookup.index: continue
        ema_val = ema_lookup.loc[ts]
        if pd.isna(ema_val): continue
        di = tr["direction"]
        cur_close = float(tr["close_at_breach"])
        if di == 1 and cur_close <= ema_val: continue
        if di == -1 and cur_close >= ema_val: continue
        # RTH only at entry
        if sessions[e] != "RTH":
            continue

        entry_px = float(opens[e])
        target = float(tr["target"])
        prior_sl = float(tr["stop"])
        eod = int(next_eod[e])

        r = sim_1ctr_clean(e, di, entry_px, target, prior_sl, eod,
                              opens, highs, lows, closes)
        if r is None: continue
        last_chain_exit = r["exit_idx_global"]

        rows.append({
            "signal_ts": ts,
            "entry_1s_idx": e,
            "entry_ts": ts_close_1s[e],
            "entry_px": entry_px,
            "exit_1s_idx": r["exit_idx_global"],
            "exit_ts": ts_close_1s[r["exit_idx_global"]],
            "exit_px": r["exit_px"],
            "outcome": r["outcome"],
            "direction": di,
            "breach_level": float(tr["breach_level"]),
            "target": target,
            "prior_sl": prior_sl,
            "level_pair": tr["level_pair"],
            "group": assign_group(tr["level_pair"]),
            "pnl_pts": r["pnl_pts"],
            "pnl_$": r["pnl_pts"] * NQ_MULT - COMMISSION,
        })

    pdf = pd.DataFrame(rows)
    pdf.to_parquet(OUT / "pandas_v0_2025_clean_1s_trades.parquet")
    print(f"  pandas trades: {len(pdf):,}")
    print(f"  pandas total PnL: ${pdf['pnl_$'].sum():+,.0f}")

    # ---- Compare to NT 1s ----
    print(f"\n[5] Reconciliation vs NT 1s clean...")
    ndf = pd.read_parquet(OUT / "nt_v0_2025_clean_1s_trades.parquet")
    ndf["entry_dt"] = pd.to_datetime(ndf["c1_fill_ts"], unit="ns",
                                          utc=True)
    ndf["exit_dt"] = pd.to_datetime(ndf["exit_ts"], unit="ns",
                                          utc=True)
    ndf["signal_ts"] = ndf["entry_dt"] - pd.Timedelta(seconds=1)
    ndf["pnl_$"] = ndf["c1_pnl_pts"] * NQ_MULT - COMMISSION

    print(f"  NT 1s trades: {len(ndf):,}")
    print(f"  NT 1s total PnL: ${ndf['pnl_$'].sum():+,.0f}")
    print(f"  pandas: {len(pdf):,} trades, ${pdf['pnl_$'].sum():+,.0f}")
    print(f"  Δ count: {len(pdf) - len(ndf):,}")
    print(f"  Δ total: ${pdf['pnl_$'].sum() - ndf['pnl_$'].sum():+,.0f}")

    # ---- Match by signal_ts + direction + breach_level ----
    pdf_sorted = pdf.sort_values("signal_ts").reset_index(drop=True)
    ndf_sorted = ndf.sort_values("signal_ts").reset_index(drop=True)
    merged = pd.merge_asof(
        pdf_sorted[["signal_ts", "entry_ts", "entry_px",
                       "exit_ts", "exit_px", "outcome", "pnl_$",
                       "direction", "breach_level", "group"]]
            .rename(columns={"signal_ts": "sig_p", "entry_ts": "ent_p",
                                "entry_px": "px_p", "exit_ts": "exit_ts_p",
                                "exit_px": "expx_p",
                                "outcome": "outc_p",
                                "pnl_$": "pnl_p"}),
        ndf_sorted[["signal_ts", "entry_dt", "c1_fill_px",
                       "exit_dt", "exit_px", "exit_reason", "pnl_$",
                       "direction", "breach_level"]]
            .rename(columns={"signal_ts": "sig_n", "entry_dt": "ent_n",
                                "c1_fill_px": "px_n", "exit_dt": "exit_ts_n",
                                "exit_px": "expx_n",
                                "exit_reason": "outc_n",
                                "pnl_$": "pnl_n"}),
        left_on="sig_p", right_on="sig_n",
        by=["direction", "breach_level"],
        tolerance=pd.Timedelta(seconds=2),
        direction="nearest",
    )

    matched = merged[merged["sig_n"].notna()]
    print(f"\n  Matched (within 2s tolerance, same dir+L): {len(matched):,}")
    print(f"  Unmatched in pandas: {(~merged['sig_n'].notna()).sum():,}")
    if len(ndf) > 0:
        in_match_n = np.isin(ndf_sorted["signal_ts"].astype("int64").values,
                                matched["sig_n"].dropna().astype("int64").values)
        print(f"  Unmatched in NT: {(~in_match_n).sum():,}")

    # On matched: how many have IDENTICAL entry/exit/outcome/pnl
    if len(matched) > 0:
        m = matched.copy()
        m["same_entry_px"] = (m["px_p"] - m["px_n"]).abs() < 1e-6
        m["same_exit_px"] = (m["expx_p"] - m["expx_n"]).abs() < 1e-6
        m["same_outcome"] = (
            m["outc_p"].map({"win": "win", "loss": "loss",
                                  "eod_flat": "eod_flat"})
            == m["outc_n"].map({"win": "win", "loss": "loss",
                                     "eod_flat": "eod_flat"}))
        m["same_pnl"] = (m["pnl_p"] - m["pnl_n"]).abs() < 0.01
        m["same_entry_ts"] = (
            (pd.to_datetime(m["ent_p"]).astype("int64") -
             pd.to_datetime(m["ent_n"]).astype("int64")).abs() < 1_000_000_000)
        m["same_exit_ts"] = (
            (pd.to_datetime(m["exit_ts_p"]).astype("int64") -
             pd.to_datetime(m["exit_ts_n"]).astype("int64")).abs() < 2_000_000_000)
        n_m = len(m)
        print(f"\n  On matched ({n_m:,}):")
        print(f"    same entry_ts (within 1s): {m['same_entry_ts'].sum():,} ({100*m['same_entry_ts'].mean():.2f}%)")
        print(f"    same entry_px: {m['same_entry_px'].sum():,} ({100*m['same_entry_px'].mean():.2f}%)")
        print(f"    same exit_ts (within 2s): {m['same_exit_ts'].sum():,} ({100*m['same_exit_ts'].mean():.2f}%)")
        print(f"    same exit_px: {m['same_exit_px'].sum():,} ({100*m['same_exit_px'].mean():.2f}%)")
        print(f"    same outcome: {m['same_outcome'].sum():,} ({100*m['same_outcome'].mean():.2f}%)")
        print(f"    same pnl (±$0.01): {m['same_pnl'].sum():,} ({100*m['same_pnl'].mean():.2f}%)")

        # Mismatches
        mismatch = m[~m["same_pnl"]]
        if len(mismatch) > 0:
            print(f"\n  First 20 PnL mismatches:")
            print(f"    {'sig':<26} {'dir':>3} {'L':>8}  "
                  f"{'pp':>8} {'pn':>8} {'Δ':>7}  "
                  f"{'epx_p':>9} {'epx_n':>9}  "
                  f"{'xpx_p':>9} {'xpx_n':>9}  "
                  f"{'outc_p':<9} {'outc_n':<9}")
            for _, row in mismatch.head(20).iterrows():
                print(f"    {str(row['sig_p'])[:26]:<26} "
                      f"{int(row['direction']):>3} "
                      f"{row['breach_level']:>8.2f}  "
                      f"{row['pnl_p']:>+7.0f} {row['pnl_n']:>+7.0f} "
                      f"{row['pnl_p']-row['pnl_n']:>+6.0f}  "
                      f"{row['px_p']:>9.2f} {row['px_n']:>9.2f}  "
                      f"{row['expx_p']:>9.2f} {row['expx_n']:>9.2f}  "
                      f"{str(row['outc_p'])[:9]:<9} "
                      f"{str(row['outc_n'])[:9]:<9}")

    print(f"\n[done] runtime: {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
