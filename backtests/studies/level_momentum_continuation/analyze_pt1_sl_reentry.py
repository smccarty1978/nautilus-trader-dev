"""PT1 + tight SL + same-direction re-entry — conservative 1s sweep.

Universe: NQ.v.0 RTH 2024+2025, all 3 groups, EMA13 filter on triggers.

Position structure (every signal):
  2 contracts at next 1s open after 1m trigger.
  C1: limit at entry +/- PT1
  C2: runner, full PT (next_level - 2.5), stop initially = SL, then BE+1tick
  Initial SL: entry +/- SL_pts (REPLACES prior_level SL)

Conservative intrabar (mandatory):
  - SL beats PT1 in same bar (both contracts SL fill if both touched)
  - SL beats full PT (general rule)
  - After PT1 armed: BE beats full PT in same bar
  - BE_DELAY = 1 bar (BE active starting bar AFTER PT1 fire)

Slippage:
  - No slippage on entries or PT fills
  - 0.5 tick (0.125 pt) ADVERSE on all stop fills (initial SL + BE)

Sweep:
  PT1 = [3.5, 4.0]
  SL  = [2.0, 2.5, 3.0, 3.5, 4.0, 4.5, 5.0, 5.5, 6.0, 7.0, 8.0, 10.0]
  Variant = [no_reentry, max_1_reentry]

Re-entry: only if initial trade hit FULL SL before PT1.
  Window: 10 min after SL fill
  Trigger: 1m bar close > L (long) AND close > open AND close > EMA13
  Same 2-contract structure with same PT1/SL/runner.
  Max 1 re-entry per original signal.

Validation: 1s backtest is exploratory. Promising cells to be
tick-validated separately on 2026.
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
from studies.level_momentum_continuation.analyze_breakout_filter import (
    detect_triggers_breakout, assign_group,
)
from studies.level_momentum_continuation.analyze_1s_precision import (
    annotate_sessions_1s, precompute_eod_1s, map_1m_trigger_to_1s_entry,
)

OUT = Path("studies/level_momentum_continuation/results_breakout")
OUT.mkdir(parents=True, exist_ok=True)

NQ_MULT = 20.0
COMMISSION = 0.25  # round-trip per contract in pts ($5)
TICK_SIZE = 0.25
SLIP_PTS = 0.125    # 0.5 tick on stop fills
BE_OFFSET = TICK_SIZE   # +1 tick BE
BE_DELAY = 1            # bars

PT1_GRID = [3.5, 4.0]
SL_GRID = [2.0, 2.5, 3.0, 3.5, 4.0, 4.5, 5.0, 5.5, 6.0, 7.0, 8.0, 10.0]
REENTRY_WINDOW_SECS = 600   # 10 min
EMA_PERIOD = 13


# ---------------- Per-trade simulation ----------------

def sim_trade(entry_idx, di, entry_px, full_pt, eod_idx,
              pt1_pts, sl_pts,
              opens, highs, lows, closes):
    """Simulate one 2-contract PT1+SL trade.

    Returns dict with c1_outcome, c2_outcome, exit_idx_global, etc.
    Conservative: SL beats PT in same bar.
    BE_DELAY = 1 bar after PT1 fire.
    Slippage 0.125 pt on all stop fills.
    """
    n = len(highs)
    last = min(eod_idx, n - 1)
    if entry_idx >= n or last < entry_idx:
        return None

    # Compute price levels
    if di == 1:
        sl_px = entry_px - sl_pts
        sl_fill = sl_px - SLIP_PTS
        pt1_px = entry_px + pt1_pts
        be_px = entry_px + BE_OFFSET
        be_fill = be_px - SLIP_PTS
    else:
        sl_px = entry_px + sl_pts
        sl_fill = sl_px + SLIP_PTS
        pt1_px = entry_px - pt1_pts
        be_px = entry_px - BE_OFFSET
        be_fill = be_px + SLIP_PTS

    # Phase 1: walk until PT1 or SL on full position (both contracts)
    nbars = last - entry_idx + 1
    pt1_at = -1
    for s in range(nbars):
        i = entry_idx + s
        h = highs[i]; l = lows[i]
        if di == 1:
            sl_hit = (l <= sl_px)
            pt1_hit = (h >= pt1_px)
        else:
            sl_hit = (h >= sl_px)
            pt1_hit = (l <= pt1_px)
        # Conservative: SL beats PT same bar (both contracts stop)
        if sl_hit:
            c1_pnl = (sl_fill - entry_px) * di - COMMISSION
            c2_pnl = (sl_fill - entry_px) * di - COMMISSION
            return {
                "c1_outcome": "sl_before_pt1",
                "c2_outcome": "sl_before_pt1",
                "c1_pnl_pts": float(c1_pnl),
                "c2_pnl_pts": float(c2_pnl),
                "exit_idx_global": i,
                "pt1_at_global": -1,
            }
        if pt1_hit:
            pt1_at = s
            break

    if pt1_at < 0:
        # Neither PT1 nor SL hit by EOD — flat at last close
        last_close = closes[entry_idx + nbars - 1]
        c1_pnl = (last_close - entry_px) * di - COMMISSION
        c2_pnl = (last_close - entry_px) * di - COMMISSION
        return {
            "c1_outcome": "eod_flat",
            "c2_outcome": "eod_flat",
            "c1_pnl_pts": float(c1_pnl),
            "c2_pnl_pts": float(c2_pnl),
            "exit_idx_global": entry_idx + nbars - 1,
            "pt1_at_global": -1,
        }

    # PT1 fired at pt1_at — C1 closes at PT1
    c1_pnl = (pt1_px - entry_px) * di - COMMISSION
    pt1_at_global = entry_idx + pt1_at

    # Phase 2: C2 with BE+1tick (after BE_DELAY) and full PT
    # Conservative: BE beats PT same bar
    c2_start = pt1_at + BE_DELAY
    if c2_start >= nbars:
        # No bars left for C2 — flat at PT1 bar's close
        last_close = closes[entry_idx + nbars - 1]
        c2_pnl = (last_close - entry_px) * di - COMMISSION
        return {
            "c1_outcome": "pt1",
            "c2_outcome": "eod_flat",
            "c1_pnl_pts": float(c1_pnl),
            "c2_pnl_pts": float(c2_pnl),
            "exit_idx_global": pt1_at_global,
            "pt1_at_global": pt1_at_global,
        }

    for s in range(c2_start, nbars):
        i = entry_idx + s
        h = highs[i]; l = lows[i]
        if di == 1:
            be_hit = (l <= be_px)
            pt_hit = (h >= full_pt)
        else:
            be_hit = (h >= be_px)
            pt_hit = (l <= full_pt)
        # Conservative: BE beats full PT same bar
        if be_hit:
            c2_pnl = (be_fill - entry_px) * di - COMMISSION
            return {
                "c1_outcome": "pt1",
                "c2_outcome": "be_stop",
                "c1_pnl_pts": float(c1_pnl),
                "c2_pnl_pts": float(c2_pnl),
                "exit_idx_global": i,
                "pt1_at_global": pt1_at_global,
            }
        if pt_hit:
            c2_pnl = (full_pt - entry_px) * di - COMMISSION
            return {
                "c1_outcome": "pt1",
                "c2_outcome": "win",
                "c1_pnl_pts": float(c1_pnl),
                "c2_pnl_pts": float(c2_pnl),
                "exit_idx_global": i,
                "pt1_at_global": pt1_at_global,
            }

    # EOD on C2
    last_close = closes[entry_idx + nbars - 1]
    c2_pnl = (last_close - entry_px) * di - COMMISSION
    return {
        "c1_outcome": "pt1",
        "c2_outcome": "eod_flat",
        "c1_pnl_pts": float(c1_pnl),
        "c2_pnl_pts": float(c2_pnl),
        "exit_idx_global": entry_idx + nbars - 1,
        "pt1_at_global": pt1_at_global,
    }


# ---------------- Re-entry detection ----------------

def find_reentry(sl_idx_global, di, breach_L,
                  bars_1m_index_arr,    # array of 1m ts_close (UTC)
                  bars_1m_open_arr, bars_1m_close_arr,
                  bars_1m_ema13_arr,
                  ts_close_1s,          # array of 1s ts_close
                  window_secs=REENTRY_WINDOW_SECS):
    """After SL hit at sl_idx_global, look for re-entry trigger
    in the next window_secs of 1m bars.

    Trigger:
      Long: 1m close > L AND close > open AND close > EMA13
      Short: invert
    Returns: re-entry 1s index (entry on next 1s open after re-cross
    1m close), or -1 if no re-entry.
    """
    sl_ts = ts_close_1s[sl_idx_global]   # numpy datetime64 ns
    deadline_ts = sl_ts + np.timedelta64(window_secs, "s")
    # Find 1m bars in [sl_ts, deadline_ts]
    lo = np.searchsorted(bars_1m_index_arr, sl_ts, side="right")
    hi = np.searchsorted(bars_1m_index_arr, deadline_ts, side="right")
    for j in range(lo, hi):
        c = bars_1m_close_arr[j]
        o = bars_1m_open_arr[j]
        ema = bars_1m_ema13_arr[j]
        if di == 1:
            if c > breach_L and c > o and c > ema:
                # Re-entry at next 1s after this 1m close
                rc_ts = bars_1m_index_arr[j]
                target_ts = rc_ts + np.timedelta64(1, "s")
                idx = np.searchsorted(ts_close_1s, target_ts)
                if idx < len(ts_close_1s) and ts_close_1s[idx] == target_ts:
                    return idx
        else:
            if c < breach_L and c < o and c < ema:
                rc_ts = bars_1m_index_arr[j]
                target_ts = rc_ts + np.timedelta64(1, "s")
                idx = np.searchsorted(ts_close_1s, target_ts)
                if idx < len(ts_close_1s) and ts_close_1s[idx] == target_ts:
                    return idx
    return -1


# ---------------- Harvest with EMA13 ----------------

def harvest_with_ema13(year):
    """Load 1s + 1m + EMA13 + triggers + chain. Returns trades list +
    arrays needed for re-entry detection."""
    print(f"\n[{year}] loading & harvesting...", flush=True)
    bars_1s = load_v0_1s(Path(f"data/raw/NQ_v0_1s_{year}.parquet"))
    bars_1s = annotate_sessions_1s(bars_1s)
    bars_1m = bars_1s[
        ["open", "high", "low", "close", "volume"]
    ].resample("1min", label="right", closed="right").agg({
        "open": "first", "high": "max", "low": "min",
        "close": "last", "volume": "sum"
    }).dropna(subset=["open", "high", "low", "close"])
    bars_1m = annotate_sessions_ct(bars_1m)
    # EMA13 on 1m close
    bars_1m["ema13"] = bars_1m["close"].ewm(
        span=EMA_PERIOD, adjust=False).mean()

    triggers = detect_triggers_breakout(bars_1m)
    print(f"  triggers: {len(triggers):,}", flush=True)

    bars_1s_reset = bars_1s.reset_index(drop=False)
    opens = bars_1s_reset["open"].values.astype(np.float64)
    highs = bars_1s_reset["high"].values.astype(np.float64)
    lows = bars_1s_reset["low"].values.astype(np.float64)
    closes = bars_1s_reset["close"].values.astype(np.float64)
    sessions = bars_1s_reset["session"].values
    ts_close_1s_pd = pd.DatetimeIndex(bars_1s_reset["ts_close"])
    if ts_close_1s_pd.tz is None:
        ts_close_1s_pd = ts_close_1s_pd.tz_localize("UTC")
    else:
        ts_close_1s_pd = ts_close_1s_pd.tz_convert("UTC")
    ts_close_1s_np = ts_close_1s_pd.values.astype("datetime64[ns]")
    next_eod = precompute_eod_1s(bars_1s_reset)

    # 1m arrays for re-entry detection
    bars_1m_idx = bars_1m.index.values.astype("datetime64[ns]")
    bars_1m_open = bars_1m["open"].values.astype(np.float64)
    bars_1m_close = bars_1m["close"].values.astype(np.float64)
    bars_1m_ema = bars_1m["ema13"].values.astype(np.float64)
    # ema13_at_trigger map: ts -> ema value
    ema_lookup = pd.Series(bars_1m_ema, index=bars_1m.index)

    # Build chain on baseline (no policy) just to define trade population
    # Use prior_level_SL + full_PT so we get same trade IDs
    last_chain_exit = -1
    trades_meta = []
    for tr in triggers:
        ts = pd.Timestamp(tr["bar_ts_close"])
        if ts.tz is None: ts = ts.tz_localize("UTC")
        else: ts = ts.tz_convert("UTC")
        e = map_1m_trigger_to_1s_entry(ts, ts_close_1s_pd)
        if e < 0: continue
        if e <= last_chain_exit: continue
        di = tr["direction"]
        # Apply EMA13 filter
        if ts not in ema_lookup.index: continue
        ema_val = ema_lookup.loc[ts]
        if pd.isna(ema_val): continue
        cur_close = float(tr["close_at_breach"])
        if di == 1 and cur_close <= ema_val:
            # advance chain by skipping this trigger but no entry
            continue
        if di == -1 and cur_close >= ema_val:
            continue
        # Apply RTH filter
        if sessions[e] != "RTH":
            continue
        entry_px = float(opens[e])
        # Use prior_level_SL for chain advancement (longest exit)
        # Run baseline simulation with prior_sl + full PT (no PT1)
        from studies.level_momentum_continuation.analyze_2contract_tp5_be import (
            sim_baseline_path,
        )
        bp = sim_baseline_path(
            e, di, entry_px, float(tr["target"]),
            float(tr["stop"]), int(next_eod[e]),
            highs, lows, closes)
        if bp is None: continue
        last_chain_exit = bp["exit_idx_global"]
        trades_meta.append({
            "year": year,
            "entry_1s_idx": e,
            "entry_px": entry_px,
            "direction": di,
            "breach_level": float(tr["breach_level"]),
            "target": float(tr["target"]),
            "prior_sl": float(tr["stop"]),
            "eod_idx": int(next_eod[e]),
            "level_pair": tr["level_pair"],
            "group": assign_group(tr["level_pair"]),
            "trigger_ts": ts,
        })

    print(f"  RTH+EMA13 trades on baseline chain: "
          f"{len(trades_meta):,}", flush=True)
    return (trades_meta, opens, highs, lows, closes,
            ts_close_1s_np, bars_1m_idx, bars_1m_open,
            bars_1m_close, bars_1m_ema)


# ---------------- Per-cell sweep ----------------

def run_cell(trades_meta, year_arrays, pt1_pts, sl_pts, with_reentry):
    rows = []
    for t in trades_meta:
        y = t["year"]
        opens, highs, lows, closes, ts1s_np, b1m_idx, b1m_o, b1m_c, b1m_e = year_arrays[y]
        r = sim_trade(
            t["entry_1s_idx"], t["direction"], t["entry_px"],
            t["target"], t["eod_idx"],
            pt1_pts, sl_pts,
            opens, highs, lows, closes)
        if r is None: continue
        # Re-entry?
        re_r = None
        if (with_reentry and
                r["c1_outcome"] == "sl_before_pt1"):
            re_idx = find_reentry(
                r["exit_idx_global"], t["direction"],
                t["breach_level"],
                b1m_idx, b1m_o, b1m_c, b1m_e,
                ts1s_np)
            if re_idx >= 0 and re_idx <= t["eod_idx"]:
                re_entry_px = float(opens[re_idx])
                re_r = sim_trade(
                    re_idx, t["direction"], re_entry_px,
                    t["target"], t["eod_idx"],
                    pt1_pts, sl_pts,
                    opens, highs, lows, closes)
        # Compute total PnL
        # Per spec: 2 contracts, each commissioned ($5 RT) on entry
        # COMMISSION already applied per contract in sim_trade
        total_pnl_pts_initial = r["c1_pnl_pts"] + r["c2_pnl_pts"]
        re_pnl_pts = 0.0
        re_outcome_c1 = None
        re_outcome_c2 = None
        if re_r is not None:
            re_pnl_pts = re_r["c1_pnl_pts"] + re_r["c2_pnl_pts"]
            re_outcome_c1 = re_r["c1_outcome"]
            re_outcome_c2 = re_r["c2_outcome"]
        rows.append({
            "year": y,
            "trigger_ts": t["trigger_ts"],
            "group": t["group"],
            "level_pair": t["level_pair"],
            "direction": t["direction"],
            "c1_outcome": r["c1_outcome"],
            "c2_outcome": r["c2_outcome"],
            "c1_pnl_pts": r["c1_pnl_pts"],
            "c2_pnl_pts": r["c2_pnl_pts"],
            "initial_pnl_pts": total_pnl_pts_initial,
            "had_reentry": re_r is not None,
            "re_c1_outcome": re_outcome_c1,
            "re_c2_outcome": re_outcome_c2,
            "re_pnl_pts": re_pnl_pts,
            "total_pnl_pts": total_pnl_pts_initial + re_pnl_pts,
            "total_pnl_dollars":
                (total_pnl_pts_initial + re_pnl_pts) * NQ_MULT,
        })
    return pd.DataFrame(rows)


def aggregate_cell(df, label):
    """Compute metrics for one cell."""
    n = len(df)
    if n == 0: return None
    ttl = float(df["total_pnl_dollars"].sum())
    n_pt1 = int((df["c1_outcome"] == "pt1").sum())
    n_sl_init = int((df["c1_outcome"] == "sl_before_pt1").sum())
    n_be = int((df["c2_outcome"] == "be_stop").sum())
    n_runner_win = int((df["c2_outcome"] == "win").sum())
    n_re = int(df["had_reentry"].sum())
    re_df = df[df["had_reentry"]]
    re_total = float(re_df["re_pnl_pts"].sum() * NQ_MULT)
    n_re_pt1 = int((re_df["re_c1_outcome"] == "pt1").sum())
    n_re_runner_win = int((re_df["re_c2_outcome"] == "win").sum())
    out = {
        "label": label, "n": n,
        "total_$": ttl, "$/tr": ttl / n,
        "pt1_pct": 100 * n_pt1 / n,
        "sl_init_pct": 100 * n_sl_init / n,
        "be_pct": 100 * n_be / n,
        "runner_win_pct": 100 * n_runner_win / n,
        "n_reentry": n_re,
        "reentry_pnl_$": re_total,
        "reentry_pt1_pct": 100 * n_re_pt1 / max(1, n_re),
        "reentry_runner_win_pct": 100 * n_re_runner_win / max(1, n_re),
    }
    for yr in (2024, 2025):
        sg = df[df["year"] == yr]
        if len(sg):
            out[f"y{yr}_total_$"] = float(sg["total_pnl_dollars"].sum())
            out[f"y{yr}_n"] = len(sg)
    # Max drawdown (per-trade cumulative)
    if n > 0:
        df_sorted = df.sort_values("trigger_ts")
        cum = df_sorted["total_pnl_dollars"].cumsum().values
        peak = np.maximum.accumulate(cum)
        dd = cum - peak
        out["max_dd_$"] = float(dd.min())
    return out


# ---------------- Post-SL descriptive study ----------------

def descriptive_post_sl(trades_meta, year_arrays, pt1_pts, sl_pts,
                          window_secs=REENTRY_WINDOW_SECS):
    """For each initial trade that hits SL before PT1, classify
    post-SL forward path within window:
      true_fail: never reclaims breach L
      v_recovery: reclaims AND reaches PT1 of re-entry
      missed_winner: reclaims AND reaches full PT
      chop_fail: reclaims but fails again (re-entry would SL)
    """
    rows = []
    for t in trades_meta:
        y = t["year"]
        opens, highs, lows, closes, ts1s_np, b1m_idx, b1m_o, b1m_c, b1m_e = year_arrays[y]
        # Run initial sim to identify SL-before-PT1 trades
        r = sim_trade(
            t["entry_1s_idx"], t["direction"], t["entry_px"],
            t["target"], t["eod_idx"],
            pt1_pts, sl_pts,
            opens, highs, lows, closes)
        if r is None: continue
        if r["c1_outcome"] != "sl_before_pt1":
            continue
        # Look for re-entry
        sl_idx = r["exit_idx_global"]
        re_idx = find_reentry(
            sl_idx, t["direction"], t["breach_level"],
            b1m_idx, b1m_o, b1m_c, b1m_e, ts1s_np, window_secs)
        bucket = "true_fail"
        if re_idx >= 0 and re_idx <= t["eod_idx"]:
            # Simulate re-entry to determine outcome
            re_entry_px = float(opens[re_idx])
            re_r = sim_trade(
                re_idx, t["direction"], re_entry_px,
                t["target"], t["eod_idx"],
                pt1_pts, sl_pts,
                opens, highs, lows, closes)
            if re_r is None:
                bucket = "true_fail"
            else:
                if re_r["c2_outcome"] == "win":
                    bucket = "missed_winner"
                elif re_r["c1_outcome"] == "pt1":
                    bucket = "v_recovery"
                else:
                    bucket = "chop_fail"
        rows.append({
            "year": y, "group": t["group"],
            "level_pair": t["level_pair"],
            "direction": t["direction"],
            "bucket": bucket,
        })
    return pd.DataFrame(rows)


# ---------------- Main ----------------

def main():
    t0 = time.time()
    all_trades = []
    year_arrays = {}
    for year in (2024, 2025):
        meta, *arr = harvest_with_ema13(year)
        year_arrays[year] = tuple(arr)
        all_trades.extend(meta)
    print(f"\nTotal RTH+EMA13 trades: {len(all_trades):,}", flush=True)

    # ---- Main sweep ----
    print(f"\n{'='*78}\nSWEEP — {len(PT1_GRID)} PT1 × {len(SL_GRID)} SL × "
          f"2 reentry variants × 3 groups\n{'='*78}", flush=True)
    summary_rows = []
    for pt1 in PT1_GRID:
        for sl in SL_GRID:
            for variant in ("no_reentry", "with_reentry"):
                tag = f"PT1={pt1} SL={sl} {variant}"
                df = run_cell(
                    all_trades, year_arrays, pt1, sl,
                    with_reentry=(variant == "with_reentry"))
                if df.empty: continue
                # Aggregate combined
                agg = aggregate_cell(df, tag)
                if agg is None: continue
                agg["pt1"] = pt1; agg["sl"] = sl
                agg["variant"] = variant; agg["group"] = "ALL"
                summary_rows.append(agg)
                # Per group
                for grp in ("A_25pt", "B_14_15pt", "C_10_11pt"):
                    g = df[df["group"] == grp]
                    if len(g) == 0: continue
                    a = aggregate_cell(g, f"{tag} [{grp}]")
                    if a is None: continue
                    a["pt1"] = pt1; a["sl"] = sl
                    a["variant"] = variant; a["group"] = grp
                    summary_rows.append(a)
    sweep_df = pd.DataFrame(summary_rows)
    sweep_df.to_csv(OUT / "pt1_sl_reentry_sweep.csv", index=False)

    # ---- Print headline tables ----
    print(f"\n{'='*78}\nCOMBINED A+B+C — top cells by total $\n{'='*78}")
    for variant in ("no_reentry", "with_reentry"):
        v = sweep_df[(sweep_df["variant"] == variant) &
                      (sweep_df["group"] == "ALL")]
        v_pos = v[(v.get("y2024_total_$", 0) > 0) &
                   (v.get("y2025_total_$", 0) > 0)]
        print(f"\n--- {variant} (combined A+B+C) ---")
        print(f"  {'PT1':>4} {'SL':>5}  {'n':>6} "
              f"{'total_$':>12} {'$/tr':>7}  "
              f"{'pt1%':>5} {'sl_init%':>9} {'be%':>5} "
              f"{'runwin%':>8} {'2024_$':>10} {'2025_$':>10}  "
              f"{'maxDD':>10}  {'reentry_n':>9}")
        for _, r in v.sort_values("total_$",
                                       ascending=False).head(8).iterrows():
            tag = "✓" if (r.get("y2024_total_$", 0) > 0
                          and r.get("y2025_total_$", 0) > 0) else " "
            print(f"  {r['pt1']:>4.1f} {r['sl']:>5.1f} "
                  f"{int(r['n']):>6,} "
                  f"{r['total_$']:>+11,.0f} "
                  f"{r['$/tr']:>+6.2f} "
                  f"{r['pt1_pct']:>4.1f}% "
                  f"{r['sl_init_pct']:>8.1f}% "
                  f"{r['be_pct']:>4.1f}% "
                  f"{r['runner_win_pct']:>7.1f}% "
                  f"{r.get('y2024_total_$', 0):>+9,.0f} "
                  f"{r.get('y2025_total_$', 0):>+9,.0f} "
                  f"{r.get('max_dd_$', 0):>+9,.0f} "
                  f"{int(r['n_reentry']):>9,}  {tag}")

    print(f"\n--- Per-group view (no_reentry, ALL/A/B/C) ---")
    for grp in ("ALL", "A_25pt", "B_14_15pt", "C_10_11pt"):
        v = sweep_df[(sweep_df["variant"] == "no_reentry") &
                      (sweep_df["group"] == grp)]
        print(f"\n  [{grp}] top 3 by total $:")
        for _, r in v.sort_values("total_$",
                                       ascending=False).head(3).iterrows():
            print(f"    PT1={r['pt1']:.1f} SL={r['sl']:.1f}  "
                  f"total ${r['total_$']:>+,.0f}  "
                  f"$/tr {r['$/tr']:>+.2f}  "
                  f"(2024 ${r.get('y2024_total_$', 0):>+,.0f} / "
                  f"2025 ${r.get('y2025_total_$', 0):>+,.0f})")

    # ---- Descriptive post-SL study ----
    print(f"\n{'='*78}\nDESCRIPTIVE POST-SL STUDY — bucket counts per group, PT1, SL\n{'='*78}", flush=True)
    desc_rows = []
    # For brevity, run desc only on a subset of (PT1, SL) values
    desc_pt1_sl = [(3.5, 3.0), (3.5, 4.0), (3.5, 5.0), (3.5, 8.0),
                    (4.0, 3.0), (4.0, 4.0), (4.0, 5.0), (4.0, 8.0)]
    for pt1, sl in desc_pt1_sl:
        df = descriptive_post_sl(all_trades, year_arrays, pt1, sl)
        if df.empty: continue
        for grp in ("A_25pt", "B_14_15pt", "C_10_11pt"):
            g = df[df["group"] == grp]
            n = len(g)
            if n == 0: continue
            c = g["bucket"].value_counts()
            row = {"pt1": pt1, "sl": sl, "group": grp, "n_stopped": n}
            for bk in ("true_fail", "v_recovery",
                       "missed_winner", "chop_fail"):
                row[f"{bk}_n"] = int(c.get(bk, 0))
                row[f"{bk}_pct"] = 100 * c.get(bk, 0) / n
            desc_rows.append(row)
    desc_df = pd.DataFrame(desc_rows)
    desc_df.to_csv(OUT / "pt1_sl_descriptive.csv", index=False)
    print(f"\nPer-cell descriptive (n_stopped, %s in each bucket):")
    print(f"  {'PT1':>4} {'SL':>5} {'group':<14} {'n_sl':>6}  "
          f"{'true_fail':>11} {'v_recov':>9} {'missed_win':>11} "
          f"{'chop_fail':>11}")
    for _, r in desc_df.iterrows():
        print(f"  {r['pt1']:>4.1f} {r['sl']:>5.1f} {r['group']:<14} "
              f"{int(r['n_stopped']):>6,}  "
              f"{r['true_fail_pct']:>9.1f}% "
              f"{r['v_recovery_pct']:>7.1f}% "
              f"{r['missed_winner_pct']:>9.1f}% "
              f"{r['chop_fail_pct']:>9.1f}%")

    print(f"\n[done] runtime: {time.time()-t0:.0f}s")
    print(f"saved: {OUT / 'pt1_sl_reentry_sweep.csv'}")
    print(f"       {OUT / 'pt1_sl_descriptive.csv'}")


if __name__ == "__main__":
    main()
