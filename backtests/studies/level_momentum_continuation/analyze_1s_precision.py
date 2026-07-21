"""1s-precision validation of SL=30 + BE=2.5 + skip-while-open.

Hybrid simulation:
  - Triggers detected on 1m bars (Goldilocks signal is a 1m close
    above level — that's the strategy spec)
  - Trade execution walks 1s bars (BE arming, BE-stop, cat-stop,
    target checks at 1s granularity)
  - Skip-while-open at 1s precision (chain holds until 1s exit)
  - EOD flat at 16:00 CT

vs prior 1m-bar simulation:
  Prior: BE armed at 1m bar close (~60s lag from MFE crossing +2.5)
  Here:  BE armed at 1s bar close (~1s lag from MFE crossing +2.5)

Vectorized per-trade exit search using numpy argmax.

Configuration:
  SL = 30 pts (cat stop)
  BE = 2.5 pts (move stop to entry once MFE >= this)
  Single position (skip-while-open)
  EOD flat at 16:00 CT
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


OUT = Path(
    "studies/level_momentum_continuation/results_1s_precision")
OUT.mkdir(parents=True, exist_ok=True)

SL_PTS = 30.0
BE_PTS = 2.5
COMMISSION_PTS = 0.25
NQ_DOLLAR_PER_PT = 20.0
TICK_SIZE = 0.25
EOD_HOUR_CT = 16
# 0 = pessimistic (BE stop can fire same 1s bar as arming)
# 1 = realistic (NT places stop after arm bar; next 1s onward)
BE_STOP_DELAY_BARS = 1
# BE stop price offset in TICKS in favorable direction from entry.
# 0 = stop at entry (gross 0, net = -commission per trade)
# 1 = stop at entry + 1 tick (long): exit covers commission
BE_STOP_OFFSET_TICKS = 1


def annotate_sessions_1s(bars_1s: pd.DataFrame) -> pd.DataFrame:
    """Same logic as annotate_sessions_ct but for 1s bars."""
    out = bars_1s.copy()
    if out.index.tz is None:
        out.index = out.index.tz_localize("UTC")
    ts_ct = out.index.tz_convert("America/Chicago")
    from datetime import time as dt_time
    rth_start = dt_time(8, 30, 0)
    rth_end = dt_time(15, 0, 0)
    times = ts_ct.time
    weekday = ts_ct.weekday
    is_weekday = weekday < 5
    is_rth = is_weekday & (times >= rth_start) & (times < rth_end)
    session = np.where(is_rth, "RTH", "ETH")
    out["ts_ct"] = ts_ct
    out["session"] = session
    out["year"] = ts_ct.year
    out["hour_ct"] = ts_ct.hour
    return out


def filter_roll_window_1s(bars_1s: pd.DataFrame,
                                  window_days: int) -> pd.DataFrame:
    """Drop 1s bars within ±window_days of quarterly rolls."""
    if window_days <= 0:
        return bars_1s
    from datetime import date
    years = sorted(set(bars_1s["year"].values))
    drop_dates: set[date] = set()
    for yr in years:
        for month in (3, 6, 9, 12):
            first = date(int(yr), month, 1)
            offset = (3 - first.weekday()) % 7
            third_thursday = date(int(yr), month,
                                          1 + offset + 14)
            for delta in range(-window_days, window_days + 1):
                drop_dates.add(third_thursday +
                                  pd.Timedelta(days=delta).to_pytimedelta())
    ct_dates = bars_1s["ts_ct"].dt.date
    keep = ~ct_dates.isin(drop_dates)
    return bars_1s[keep].copy()


def simulate_trade_1s(entry_1s_idx: int, di: int,
                            entry_px: float, target: float,
                            sl_px: float, be_px: float,
                            be_threshold: float,
                            eod_idx: int,
                            opens_1s: np.ndarray,
                            highs_1s: np.ndarray,
                            lows_1s: np.ndarray,
                            closes_1s: np.ndarray):
    """Vectorized single-trade simulation using 1s bars."""
    n = len(opens_1s)
    last = min(eod_idx, n - 1)
    if entry_1s_idx >= n:
        return None
    if last < entry_1s_idx:
        return None

    # Slice 1s bars from entry to EOD
    sli_h = highs_1s[entry_1s_idx : last + 1]
    sli_l = lows_1s[entry_1s_idx : last + 1]
    sli_c = closes_1s[entry_1s_idx : last + 1]
    nbars = len(sli_h)

    # be_stop_delay: bars after arming before BE stop is "active".
    # 0 = pessimistic (same-bar reversal can stop us)
    # 1 = realistic (NT places stop after arm bar; next bar onwards)
    be_stop_delay = BE_STOP_DELAY_BARS

    if di == 1:
        # Long
        running_mfe = np.maximum.accumulate(sli_h - entry_px)
        be_arm_mask = running_mfe >= be_threshold
        be_armed_at = int(np.argmax(be_arm_mask)) if be_arm_mask.any() else -1
        # Cat stop: low <= sl_px
        cat_hit = sli_l <= sl_px
        cat_idx = int(np.argmax(cat_hit)) if cat_hit.any() else -1
        # Target: high >= target
        tgt_hit = sli_h >= target
        tgt_idx = int(np.argmax(tgt_hit)) if tgt_hit.any() else -1
        # BE-stop: low <= be_px, after be_armed_at + delay
        if be_armed_at >= 0:
            start = be_armed_at + be_stop_delay
            if start < nbars:
                be_stop_hit = sli_l[start:] <= be_px
                if be_stop_hit.any():
                    be_idx = start + int(np.argmax(be_stop_hit))
                else:
                    be_idx = -1
            else:
                be_idx = -1
        else:
            be_idx = -1
    else:
        # Short
        running_mfe = np.maximum.accumulate(entry_px - sli_l)
        be_arm_mask = running_mfe >= be_threshold
        be_armed_at = int(np.argmax(be_arm_mask)) if be_arm_mask.any() else -1
        cat_hit = sli_h >= sl_px
        cat_idx = int(np.argmax(cat_hit)) if cat_hit.any() else -1
        tgt_hit = sli_l <= target
        tgt_idx = int(np.argmax(tgt_hit)) if tgt_hit.any() else -1
        if be_armed_at >= 0:
            start = be_armed_at + be_stop_delay
            if start < nbars:
                be_stop_hit = sli_h[start:] >= be_px
                if be_stop_hit.any():
                    be_idx = start + int(np.argmax(be_stop_hit))
                else:
                    be_idx = -1
            else:
                be_idx = -1
        else:
            be_idx = -1

    # Build candidate exits (idx within slice, outcome, exit_px)
    candidates = []
    if cat_idx >= 0:
        # Cat-stop fires only if it precedes BE-armed (else BE catches first)
        if be_armed_at == -1 or cat_idx < be_armed_at:
            candidates.append((cat_idx, "cat_loss", sl_px))
    if be_idx >= 0:
        candidates.append((be_idx, "be_stop", be_px))
    if tgt_idx >= 0:
        candidates.append((tgt_idx, "win", target))

    if not candidates:
        # EOD flat
        outcome = "eod_flat"
        exit_idx_in_slice = nbars - 1
        exit_px = sli_c[-1]
    else:
        # Earliest wins; ties broken by candidate order
        # (cat_loss > be_stop > win conservative)
        candidates.sort(key=lambda x: (x[0],
            0 if x[1] == "cat_loss" else (1 if x[1] == "be_stop" else 2)))
        exit_idx_in_slice, outcome, exit_px = candidates[0]

    pnl_gross = (exit_px - entry_px) * di
    return {
        "outcome": outcome,
        "exit_idx_global": entry_1s_idx + exit_idx_in_slice,
        "exit_px": exit_px,
        "pnl_gross": pnl_gross,
        "pnl_net": pnl_gross - COMMISSION_PTS,
        "be_armed": be_armed_at >= 0,
        "be_armed_at_global": (entry_1s_idx + be_armed_at)
                                    if be_armed_at >= 0 else -1,
    }


def precompute_eod_1s(bars_1s: pd.DataFrame) -> np.ndarray:
    """For each 1s bar idx, return idx of next 16:00 CT bar."""
    ts_ct = bars_1s["ts_ct"]
    # 16:00:00 CT bar is the one with hour=16, minute=0, second=0
    # In 1s bars, ts_close = T means the bar SPANS T-1s to T.
    # So the bar that "closes at 16:00:00" is the one ending the
    # last second before the maintenance break.
    is_eod = (ts_ct.dt.hour == EOD_HOUR_CT) & (
        ts_ct.dt.minute == 0) & (ts_ct.dt.second == 0)
    eod_indices = np.where(is_eod.values)[0]
    n = len(bars_1s)
    next_eod = np.full(n, n - 1, dtype=int)
    j = 0
    for i in range(n):
        while j < len(eod_indices) and eod_indices[j] < i:
            j += 1
        if j < len(eod_indices):
            next_eod[i] = eod_indices[j]
    return next_eod


def map_1m_trigger_to_1s_entry(trigger_ts_close, ts_close_1s):
    """Find 1s idx whose ts_close = trigger_ts_close + 1s.
    That 1s bar opens at trigger_ts_close (the entry moment)."""
    target_ts = trigger_ts_close + pd.Timedelta(seconds=1)
    idx = ts_close_1s.searchsorted(target_ts)
    if idx < len(ts_close_1s) and ts_close_1s[idx] == target_ts:
        return idx
    return -1


def fmt_p(v):
    if v is None or pd.isna(v): return "—"
    return f"{100*v:.1f}%"


def fmt_f(v, dp=2):
    if v is None or pd.isna(v): return "—"
    return f"{v:+.{dp}f}"


def fmt_d(v):
    if v is None or pd.isna(v): return "—"
    return f"${v:,.0f}"


def main():
    t0 = time.time()
    summaries = {}

    for year in [2024, 2025]:
        print(f"\n{'='*70}\n[{year}] loading 1s bars...")
        parquet = Path(f"data/raw/NQ_v0_1s_{year}.parquet")
        bars_1s = load_v0_1s(parquet)
        print(f"  {len(bars_1s):,} 1s bars")

        bars_1s = annotate_sessions_1s(bars_1s)
        print(f"[{year}] roll filter on 1s...")
        bars_1s = filter_roll_window_1s(bars_1s, 3)
        print(f"  after roll filter: {len(bars_1s):,}")

        # Resample to 1m for trigger detection
        print(f"[{year}] resampling to 1m for trigger detection...")
        bars_1m = bars_1s[
            ["open", "high", "low", "close", "volume"]
        ].resample("1min", label="right",
                          closed="right").agg({
                              "open": "first", "high": "max",
                              "low": "min", "close": "last",
                              "volume": "sum"}).dropna(
            subset=["open", "high", "low", "close"])
        bars_1m = annotate_sessions_ct(bars_1m)
        print(f"  {len(bars_1m):,} 1m bars")

        # Detect triggers
        bars_1m_reset = bars_1m.reset_index(drop=False)
        triggers = detect_triggers(bars_1m_reset)
        print(f"[{year}] {len(triggers):,} 1m Goldilocks triggers")

        # Pre-compute 1s arrays + EOD lookup
        print(f"[{year}] precomputing 1s arrays + EOD...")
        bars_1s_reset = bars_1s.reset_index(drop=False)
        opens_1s = bars_1s_reset["open"].values
        highs_1s = bars_1s_reset["high"].values
        lows_1s = bars_1s_reset["low"].values
        closes_1s = bars_1s_reset["close"].values
        # Keep tz-aware (Series, not .values which strips tz)
        ts_close_1s_pd = pd.DatetimeIndex(
            bars_1s_reset["ts_close"])
        if ts_close_1s_pd.tz is None:
            ts_close_1s_pd = ts_close_1s_pd.tz_localize("UTC")
        else:
            ts_close_1s_pd = ts_close_1s_pd.tz_convert("UTC")
        next_eod = precompute_eod_1s(bars_1s_reset)

        # Simulate each trigger with skip-while-open at 1s precision
        print(f"[{year}] simulating trades at 1s precision...")
        chains = []
        last_chain_exit_1s = -1
        skipped = 0
        sim_count = 0
        t1 = time.time()
        for tr in triggers:
            entry_1s_idx = map_1m_trigger_to_1s_entry(
                pd.Timestamp(tr.bar_ts_close).tz_convert("UTC")
                if pd.Timestamp(tr.bar_ts_close).tz is not None
                else pd.Timestamp(tr.bar_ts_close, tz="UTC"),
                ts_close_1s_pd)
            if entry_1s_idx < 0:
                continue
            # Skip-while-open: skip if entry is during prior chain
            if entry_1s_idx <= last_chain_exit_1s:
                skipped += 1
                continue
            # Compute SL price (Cat=30)
            di = tr.direction
            entry_px = float(opens_1s[entry_1s_idx])
            sl_px = entry_px - SL_PTS if di == 1 else entry_px + SL_PTS
            # BE stop offset: favorable side of entry by N ticks
            be_off = BE_STOP_OFFSET_TICKS * TICK_SIZE
            be_px = (entry_px + be_off) if di == 1 else (entry_px - be_off)
            target = float(tr.target)
            eod_idx = int(next_eod[entry_1s_idx])

            r = simulate_trade_1s(
                entry_1s_idx, di, entry_px, target, sl_px,
                be_px, BE_PTS, eod_idx,
                opens_1s, highs_1s, lows_1s, closes_1s)
            if r is None:
                continue
            r["entry_1s_idx"] = entry_1s_idx
            r["entry_px"] = entry_px
            r["direction"] = di
            r["breach_level"] = float(tr.breach_level)
            r["next_level"] = float(tr.next_level)
            r["session"] = tr.bar_session
            # Build pair label
            L_off = int(tr.breach_level - (
                int(tr.breach_level // 100) * 100))
            Y_off = int(tr.next_level - (
                int(tr.next_level // 100) * 100))
            if Y_off == 100: Y_off = 0
            r["level_pair"] = (
                f"{L_off:02d}->{Y_off:02d}_"
                f"{'long' if di == 1 else 'short'}")
            chains.append(r)
            last_chain_exit_1s = r["exit_idx_global"]
            sim_count += 1
            if sim_count % 5000 == 0:
                elapsed = time.time() - t1
                rate = sim_count / max(elapsed, 0.01)
                print(f"  ... {sim_count:,} simulated, "
                      f"{skipped:,} skipped, "
                      f"{rate:.0f} trades/s")

        df = pd.DataFrame(chains)
        df.to_csv(OUT / f"trades_1s_{year}.csv", index=False)
        print(f"[{year}] done: {len(df):,} trades, "
              f"{skipped:,} skipped (skip-while-open)")

        # Aggregate
        n = len(df)
        n_win = int((df["outcome"] == "win").sum())
        n_be = int((df["outcome"] == "be_stop").sum())
        n_cat = int((df["outcome"] == "cat_loss").sum())
        n_eod = int((df["outcome"] == "eod_flat").sum())
        mean_pnl = float(df["pnl_net"].mean())
        total_pnl = float(df["pnl_net"].sum())
        annual = total_pnl * NQ_DOLLAR_PER_PT
        armed_pct = float(df["be_armed"].mean())
        summaries[year] = {
            "n": n, "win_rate": n_win / n,
            "be_stop_rate": n_be / n,
            "cat_loss_rate": n_cat / n,
            "eod_rate": n_eod / n,
            "armed_rate": armed_pct,
            "mean_pnl_net": mean_pnl,
            "total_pnl_net": total_pnl,
            "annual_dollars": annual,
        }
        print(f"\n[{year}] OVERALL:")
        print(f"  n={n:,}, WR={fmt_p(n_win/n)}, "
              f"BE-stop={fmt_p(n_be/n)}, "
              f"cat={fmt_p(n_cat/n)}, EOD={fmt_p(n_eod/n)}")
        print(f"  Armed%={fmt_p(armed_pct)}")
        print(f"  Mean PnL net = {fmt_f(mean_pnl, 3)}")
        print(f"  Total = {fmt_f(total_pnl, 0)} pts | "
              f"Annual = {fmt_d(annual)}")

        # Per-cell
        per_cell = []
        for keys, g in df.groupby(
                ["level_pair", "session"], observed=True):
            n_g = len(g)
            n_w = int((g["outcome"] == "win").sum())
            mean_p = float(g["pnl_net"].mean())
            tot_p = float(g["pnl_net"].sum())
            per_cell.append({
                "level_pair": keys[0],
                "session": keys[1],
                "n": n_g,
                "win_rate": n_w / n_g,
                "be_stop_rate": float(
                    (g["outcome"] == "be_stop").mean()),
                "cat_loss_rate": float(
                    (g["outcome"] == "cat_loss").mean()),
                "mean_pnl_net": mean_p,
                "total_pnl_net": tot_p,
                "annual_dollars": tot_p * NQ_DOLLAR_PER_PT,
            })
        pc_df = pd.DataFrame(per_cell)
        pc_df.to_csv(OUT / f"per_cell_1s_{year}.csv", index=False)

    # Build comparison report
    print(f"\n{'='*70}\nWriting comparison report...")
    L = []
    L.append("# 1s-Precision Validation: SL=30 + BE=2.5 + skip\n")
    L.append("## Method\n")
    L.append(
        "Hybrid simulation: 1m Goldilocks triggers, 1s execution.\n\n"
        "Per-bar checks at 1s precision:\n"
        "1. Update running MFE from 1s bar's high/low\n"
        "2. Arm BE if MFE >= 2.5 (intra-1s arming)\n"
        "3. BE-stop check (if armed): low <= entry (long), "
        "high >= entry (short)\n"
        "4. Cat-stop check (only if not yet BE-armed): "
        "low <= entry-30 (long)\n"
        "5. Target check: high >= target (long)\n"
        "6. EOD flat at 16:00 CT\n\n"
        "Vectorized per-trade exit search via numpy argmax.\n\n"
        "Skip-while-open at 1s precision: chain holds slot until "
        "1s exit.\n")

    L.append("## Comparison vs prior 1m-bar simulation\n")
    L.append("| Year | 1m-bar (prior) | 1s-precision (this) | "
             "Δ |")
    L.append("|---|--:|--:|--:|")
    prior = {2024: 385000, 2025: 431000}  # SL=30+BE=2.5 single-pos
    for year in sorted(summaries.keys()):
        s = summaries[year]
        prior_v = prior.get(year, 0)
        delta = s["annual_dollars"] - prior_v
        L.append(
            f"| {year} | {fmt_d(prior_v)} | "
            f"{fmt_d(s['annual_dollars'])} | "
            f"{fmt_d(delta)} |")
    L.append("")

    L.append("## 1s-precision detail per year\n")
    for year, s in summaries.items():
        L.append(f"### {year}\n")
        L.append(f"- n trades: {s['n']:,}")
        L.append(f"- WR: {fmt_p(s['win_rate'])}")
        L.append(f"- BE-stop rate: {fmt_p(s['be_stop_rate'])}")
        L.append(f"- Cat-loss rate: {fmt_p(s['cat_loss_rate'])}")
        L.append(f"- EOD-flat rate: {fmt_p(s['eod_rate'])}")
        L.append(f"- Armed%: {fmt_p(s['armed_rate'])}")
        L.append(f"- Mean PnL net: {fmt_f(s['mean_pnl_net'], 3)}")
        L.append(f"- Annual $: {fmt_d(s['annual_dollars'])}\n")

    p = OUT / "report_1s_precision.md"
    p.write_text("\n".join(L), encoding="utf-8")
    print(f"\nReport: {p}")
    print(f"Total elapsed: {(time.time() - t0)/60:.1f} min")
    return 0


if __name__ == "__main__":
    sys.exit(main())
