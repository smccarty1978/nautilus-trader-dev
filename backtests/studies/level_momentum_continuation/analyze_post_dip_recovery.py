"""Post-dip recovery trajectory analysis.

For each RTH trade with a real dip (max_MAE >= 3), track:
  - t_dip_low: 1s index when MAE peaked (price was deepest below entry)
  - price_at_dip: low (long) or high (short) at t_dip_low
  - max_MAE_value: the dip depth in pts
  - For each elapsed-from-dip-low T (5, 10, 15, 30, 60, 120, 300 secs):
      - current price (close at that bar)
      - recovery_height = current_price - price_at_dip (long)
      - recovery_pct = recovery_height / max_MAE
        (1.0 = fully recovered to entry; 1.5 = entry + 0.5*MAE; etc.)

Bucket by trade outcome (NEW definitions):
  win_clean: outcome=win, max_MAE_full < 3 (excluded — no real dip)
  win_vshape: outcome=win, max_MAE_full >= 3 (the recovery winners)
  loss_RtB: outcome=loss, max_MFE >= 2.5 (look like v-shape early)
  loss_quick: outcome=loss, max_MFE < 2.5 (mostly excluded — no real recovery)

Goal: find a recovery threshold (e.g., recovery_pct >= 1.2 within 30s
after dip low) where v-shape winners and RtB losers diverge meaningfully.
That threshold could be a trigger for the C2 add-on.
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
from studies.level_momentum_continuation.analyze_2contract_tp5_be import (
    sim_baseline_path, assign_bucket,
    NQ_DOLLAR_PER_PT, COMMISSION_PTS,
)

OUT = Path("studies/level_momentum_continuation/results_breakout")
OUT.mkdir(parents=True, exist_ok=True)

ELAPSED_GRID = [5, 10, 15, 30, 60, 120, 300]
RECOVERY_PCT_GRID = [0.25, 0.50, 0.75, 1.00, 1.25, 1.50, 2.00]


def walk_recovery(entry_idx, di, entry_px, target_px, prior_sl_px,
                   eod_idx, highs, lows, closes):
    """Walk path. Find dip low. Track recovery from dip forward.
    Returns dict with dip info + recovery snapshots + outcome."""
    n = len(highs)
    last = min(eod_idx, n - 1)
    if entry_idx >= n or last < entry_idx:
        return None
    sli_h = highs[entry_idx : last + 1]
    sli_l = lows[entry_idx : last + 1]
    sli_c = closes[entry_idx : last + 1]
    nbars = len(sli_h)

    # Walk to find dip + outcome (using prior_SL)
    if di == 1:
        # Running mfe / mae and natural exit
        running_mae = 0.0; running_mfe = 0.0
        max_mae_at = -1   # 1s idx where MAE peaked (in slice)
        price_at_dip = entry_px
        sl_idx = -1; tgt_idx = -1
        for s in range(nbars):
            h = sli_h[s]; l = sli_l[s]
            adverse = entry_px - l
            favorable = h - entry_px
            if adverse > running_mae:
                running_mae = adverse
                max_mae_at = s
                price_at_dip = l
            if favorable > running_mfe:
                running_mfe = favorable
            # Exit checks (conservative SL beats PT)
            if sl_idx < 0 and l <= prior_sl_px:
                sl_idx = s
            if tgt_idx < 0 and h >= target_px:
                tgt_idx = s
            # Stop walking once natural exit is determined
            if sl_idx >= 0 or tgt_idx >= 0:
                break
    else:
        running_mae = 0.0; running_mfe = 0.0
        max_mae_at = -1
        price_at_dip = entry_px
        sl_idx = -1; tgt_idx = -1
        for s in range(nbars):
            h = sli_h[s]; l = sli_l[s]
            adverse = h - entry_px
            favorable = entry_px - l
            if adverse > running_mae:
                running_mae = adverse
                max_mae_at = s
                price_at_dip = h
            if favorable > running_mfe:
                running_mfe = favorable
            if sl_idx < 0 and h >= prior_sl_px:
                sl_idx = s
            if tgt_idx < 0 and l <= target_px:
                tgt_idx = s
            if sl_idx >= 0 or tgt_idx >= 0:
                break

    # Determine natural outcome
    if sl_idx == -1 and tgt_idx == -1:
        outcome = "eod_flat"
        exit_idx = nbars - 1
    elif sl_idx >= 0 and (tgt_idx == -1 or sl_idx <= tgt_idx):
        outcome = "loss"
        exit_idx = sl_idx
    else:
        outcome = "win"
        exit_idx = tgt_idx

    # Recovery snapshots from max_mae_at forward
    snapshots = {}
    if max_mae_at >= 0 and running_mae > 0:
        # For each elapsed T from dip
        for T in ELAPSED_GRID:
            t_idx = max_mae_at + T
            if t_idx > exit_idx or t_idx >= nbars:
                snapshots[f"recov_h_T{T}"] = None
                snapshots[f"recov_pct_T{T}"] = None
                continue
            cur_close = sli_c[t_idx]
            if di == 1:
                rec_height = cur_close - price_at_dip
            else:
                rec_height = price_at_dip - cur_close
            rec_pct = rec_height / running_mae
            snapshots[f"recov_h_T{T}"] = float(rec_height)
            snapshots[f"recov_pct_T{T}"] = float(rec_pct)

        # Time-to-recovery thresholds (first time recovery >= X)
        for thr in RECOVERY_PCT_GRID:
            t_first = -1
            for s in range(max_mae_at, exit_idx + 1):
                cur_close = sli_c[s]
                if di == 1:
                    rec_h = cur_close - price_at_dip
                else:
                    rec_h = price_at_dip - cur_close
                rec_pct_now = rec_h / running_mae
                if rec_pct_now >= thr:
                    t_first = s - max_mae_at
                    break
            snapshots[f"t_recov_pct_{thr}"] = t_first

    return {
        "outcome": outcome,
        "max_mae": float(running_mae),
        "max_mae_at": max_mae_at,
        "price_at_dip": float(price_at_dip),
        "max_mfe": float(running_mfe),
        "exit_idx_local": exit_idx,
        "duration_after_dip": (exit_idx - max_mae_at
                                 if max_mae_at >= 0 else 0),
        **snapshots,
    }


def main():
    t0 = time.time()
    rows = []

    for year in (2024, 2025):
        print(f"\n[{year}] loading & walking paths...")
        bars_1s = load_v0_1s(
            Path(f"data/raw/NQ_v0_1s_{year}.parquet"))
        bars_1s = annotate_sessions_1s(bars_1s)
        bars_1m = bars_1s[
            ["open", "high", "low", "close", "volume"]
        ].resample("1min", label="right", closed="right").agg({
            "open": "first", "high": "max", "low": "min",
            "close": "last", "volume": "sum"
        }).dropna(subset=["open", "high", "low", "close"])
        bars_1m = annotate_sessions_ct(bars_1m)
        triggers = detect_triggers_breakout(bars_1m)

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

        last_chain_exit = -1
        for tr in triggers:
            ts = pd.Timestamp(tr["bar_ts_close"])
            if ts.tz is None: ts = ts.tz_localize("UTC")
            else: ts = ts.tz_convert("UTC")
            e = map_1m_trigger_to_1s_entry(ts, ts_close_1s)
            if e < 0: continue
            if e <= last_chain_exit: continue
            di = tr["direction"]
            entry_px = float(opens[e])
            r = walk_recovery(
                e, di, entry_px, float(tr["target"]),
                float(tr["stop"]), int(next_eod[e]),
                highs, lows, closes)
            if r is None: continue
            last_chain_exit = e + r["exit_idx_local"]
            if sessions[e] != "RTH":
                continue
            # Bucket using full-trade max_mae
            if r["outcome"] == "win":
                bk = ("win_clean" if r["max_mae"] < 3.0
                      else "win_vshape")
            elif r["outcome"] == "loss":
                bk = ("loss_runthenbreak" if r["max_mfe"] >= 2.5
                      else "loss_quick")
            else:
                bk = "timed_out"
            rows.append({
                "year": year, "level_pair": tr["level_pair"],
                "group": assign_group(tr["level_pair"]),
                "direction": di, "outcome": r["outcome"],
                "bucket": bk, **r,
            })

    df = pd.DataFrame(rows)
    df.to_parquet(OUT / "post_dip_recovery.parquet")
    print(f"\nTotal RTH trades: {len(df):,}")

    # Restrict to trades with real dip (MAE >= 3)
    dip_df = df[df["max_mae"] >= 3.0].copy()
    print(f"Trades with MAE >= 3: {len(dip_df):,}")

    # ---- Recovery_pct distribution at each elapsed T ----
    print(f"\n{'='*78}")
    print(f"RECOVERY % at fixed times after dip low (only MAE>=3 trades)")
    print(f"  recovery_pct = (current_price - dip_low) / max_MAE")
    print(f"  1.0 = price back to entry; 1.5 = entry + 0.5*MAE")
    print(f"{'='*78}")
    for grp in ("A_25pt",):  # focus on A
        g = dip_df[dip_df["group"] == grp]
        print(f"\n[{grp}] n_dipped={len(g):,}")
        for T in ELAPSED_GRID:
            col = f"recov_pct_T{T}"
            print(f"\n  T={T}s after dip low:")
            print(f"    {'bucket':<22} {'n_alive':>8}  "
                  f"{'p25':>6} {'p50':>6} {'p75':>6} {'p90':>6}")
            for bk in ("win_vshape", "loss_runthenbreak",
                       "loss_quick"):
                sub = g[(g["bucket"] == bk) & (g[col].notna())]
                if len(sub) == 0: continue
                vals = sub[col].values
                print(f"    {bk:<22} {len(sub):>8,}  "
                      f"{np.percentile(vals,25):>+6.2f} "
                      f"{np.percentile(vals,50):>+6.2f} "
                      f"{np.percentile(vals,75):>+6.2f} "
                      f"{np.percentile(vals,90):>+6.2f}")

    # ---- Time to reach recovery thresholds ----
    print(f"\n{'='*78}")
    print(f"TIME TO REACH RECOVERY THRESHOLD (median seconds, "
          f"% of bucket reaching)")
    print(f"  '0.50' = price has bounced 50% of the way back to entry")
    print(f"  '1.00' = price back to entry level")
    print(f"  '1.50' = price 50% above entry (relative to MAE size)")
    print(f"{'='*78}")
    for grp in ("A_25pt", "B_14_15pt", "C_10_11pt"):
        g = dip_df[dip_df["group"] == grp]
        if len(g) == 0: continue
        print(f"\n[{grp}] n_dipped={len(g):,}")
        # Header
        hdr = "  bucket               "
        for thr in RECOVERY_PCT_GRID:
            hdr += f"  {thr:.2f}     "
        print(hdr)
        for bk in ("win_vshape", "loss_runthenbreak"):
            sub = g[g["bucket"] == bk]
            if len(sub) == 0: continue
            row = f"  {bk:<22}"
            for thr in RECOVERY_PCT_GRID:
                col = f"t_recov_pct_{thr}"
                if col not in sub.columns:
                    row += "    n/a   "
                    continue
                vals = sub[col].values
                hits = vals[vals >= 0]
                if len(hits) == 0:
                    row += "  never  "
                else:
                    pct = 100 * len(hits) / len(sub)
                    med = np.median(hits)
                    row += f"  {med:>3.0f}s({pct:>3.0f}%)"
            print(row)

    # ---- Divergence: recovery_pct DIFF (vshape - RtB) at each T ----
    print(f"\n{'='*78}")
    print(f"DIVERGENCE TABLE: median recovery_pct vshape - RtB")
    print(f"{'='*78}")
    for grp in ("A_25pt", "B_14_15pt", "C_10_11pt"):
        g = dip_df[dip_df["group"] == grp]
        if len(g) == 0: continue
        print(f"\n[{grp}]")
        print(f"  {'T':>4}  {'vshape p50':>11} {'RtB p50':>9} "
              f"{'diff':>7}  {'vshape p25':>11} {'RtB p75':>9} "
              f"{'sep@p25/p75':>13}")
        for T in ELAPSED_GRID:
            col = f"recov_pct_T{T}"
            v = g[(g["bucket"] == "win_vshape") & (g[col].notna())][col]
            r = g[(g["bucket"] == "loss_runthenbreak") &
                   (g[col].notna())][col]
            if len(v) == 0 or len(r) == 0: continue
            v_p50 = np.percentile(v, 50)
            r_p50 = np.percentile(r, 50)
            v_p25 = np.percentile(v, 25)
            r_p75 = np.percentile(r, 75)
            print(f"  {T:>4}  {v_p50:>+10.2f}  {r_p50:>+8.2f} "
                  f"{v_p50-r_p50:>+6.2f}  {v_p25:>+10.2f}  "
                  f"{r_p75:>+8.2f}  {v_p25-r_p75:>+12.2f}")

    # ---- Discriminator candidate: % each bucket above threshold X at time T ----
    print(f"\n{'='*78}")
    print(f"DISCRIMINATOR: % of each bucket with recov_pct >= 1.0 "
          f"(back to entry) at each T")
    print(f"{'='*78}")
    for grp in ("A_25pt", "B_14_15pt", "C_10_11pt"):
        g = dip_df[dip_df["group"] == grp]
        if len(g) == 0: continue
        print(f"\n[{grp}]")
        for T in ELAPSED_GRID:
            col = f"recov_pct_T{T}"
            v = g[(g["bucket"] == "win_vshape")]
            r = g[(g["bucket"] == "loss_runthenbreak")]
            if len(v) == 0 or len(r) == 0: continue
            v_alive = v[v[col].notna()]
            r_alive = r[r[col].notna()]
            if len(v_alive) == 0 or len(r_alive) == 0: continue
            v_above = (v_alive[col] >= 1.0).mean() * 100
            r_above = (r_alive[col] >= 1.0).mean() * 100
            v_above_125 = (v_alive[col] >= 1.25).mean() * 100
            r_above_125 = (r_alive[col] >= 1.25).mean() * 100
            v_above_150 = (v_alive[col] >= 1.50).mean() * 100
            r_above_150 = (r_alive[col] >= 1.50).mean() * 100
            print(f"  T={T:>3}s | "
                  f"vsh>=1.0: {v_above:>4.1f}%  RtB>=1.0: {r_above:>4.1f}%  "
                  f"|  vsh>=1.25: {v_above_125:>4.1f}%  RtB>=1.25: {r_above_125:>4.1f}%  "
                  f"|  vsh>=1.5: {v_above_150:>4.1f}%  RtB>=1.5: {r_above_150:>4.1f}%")

    print(f"\n[done] runtime: {time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()
