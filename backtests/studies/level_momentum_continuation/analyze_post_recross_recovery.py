"""Post-re-cross recovery trajectory analysis.

For each RTH trade:
  1. Walk path from entry
  2. Detect dip below breach (= the v-shape candidate's dip)
  3. Find re-cross: 1m bar closes back above breach
  4. At re-cross moment:
       dip_low = min low between entry and re-cross
       dip_mae = entry_px - dip_low (long)
  5. After re-cross, track for N seconds:
       price evolution
       recovery_pct = (current_price - dip_low) / dip_mae
       breach_distance = current_close - breach_level

Compare distributions:
  - win_vshape (winners that needed the dip-recovery)
  - loss_runthenbreak (losers that mimicked v-shape)

Goal: identify a post-re-cross signal that v-shape winners produce
but RtB losers don't. That signal could be:
  - "If recovery_pct >= X within Y seconds after re-cross"
  - "If breach_distance >= X within Y seconds after re-cross"
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

ELAPSED_GRID = [5, 10, 15, 30, 60, 120]
BREACH_DIST_THRESHOLDS = [0.0, 1.0, 2.0, 3.0, 5.0]


def walk_post_recross(entry_idx, di, entry_px, breach_level,
                       target_px, prior_sl_px,
                       eod_idx, opens, highs, lows, closes,
                       ts_seconds):
    """Walk path. Find re-cross. Track post-re-cross trajectory.
    Returns dict with dip info + recovery snapshots + outcome."""
    n = len(highs)
    last = min(eod_idx, n - 1)
    if entry_idx >= n or last < entry_idx:
        return None
    sli_h = highs[entry_idx : last + 1]
    sli_l = lows[entry_idx : last + 1]
    sli_c = closes[entry_idx : last + 1]
    sli_sec = ts_seconds[entry_idx : last + 1]
    nbars = len(sli_h)

    # Phase 1: detect first re-cross AFTER trade dipped below breach
    has_dipped = False
    dip_low = entry_px       # most adverse so far
    dip_low_at = -1
    recross_at = -1          # 1s idx of re-cross 1m close
    running_1m_low = float("inf")
    running_1m_high = float("-inf")
    natural_exit = -1
    natural_outcome = None

    # Walk for full sim including post-recross to find natural exit
    if di == 1:
        for s in range(nbars):
            l = sli_l[s]; h = sli_h[s]; c = sli_c[s]; sec = sli_sec[s]
            # Update dip low
            if l < dip_low:
                dip_low = l
                dip_low_at = s
            # Detect dip below breach
            if not has_dipped and l < breach_level:
                has_dipped = True
            # Update running 1m bar
            if l < running_1m_low: running_1m_low = l
            if h > running_1m_high: running_1m_high = h
            # 1m close (sec == 0)
            if sec == 0:
                if (recross_at < 0 and has_dipped
                        and c > breach_level):
                    recross_at = s
                running_1m_low = float("inf")
                running_1m_high = float("-inf")
            # Natural exit (don't break — keep walking for trajectory)
            if natural_exit < 0:
                if l <= prior_sl_px:
                    natural_exit = s
                    natural_outcome = "loss"
                elif h >= target_px:
                    natural_exit = s
                    natural_outcome = "win"
    else:
        for s in range(nbars):
            l = sli_l[s]; h = sli_h[s]; c = sli_c[s]; sec = sli_sec[s]
            # For short, "dip" is ABOVE entry (high goes up = adverse)
            if h > dip_low:  # using dip_low as "max_adverse_price"
                dip_low = h
                dip_low_at = s
            if not has_dipped and h > breach_level:
                has_dipped = True
            if l < running_1m_low: running_1m_low = l
            if h > running_1m_high: running_1m_high = h
            if sec == 0:
                if (recross_at < 0 and has_dipped
                        and c < breach_level):
                    recross_at = s
                running_1m_low = float("inf")
                running_1m_high = float("-inf")
            if natural_exit < 0:
                if h >= prior_sl_px:
                    natural_exit = s
                    natural_outcome = "loss"
                elif l <= target_px:
                    natural_exit = s
                    natural_outcome = "win"

    if natural_exit < 0:
        natural_exit = nbars - 1
        natural_outcome = "eod_flat"

    # Compute pre-recross dip MAE
    if recross_at >= 0:
        # dip_low here is the MOST adverse from entry to nbars-1, but
        # we want the dip that occurred BEFORE re-cross
        if di == 1:
            pre_dip_low = float(min(sli_l[:recross_at + 1]))
            pre_dip_mae = entry_px - pre_dip_low
        else:
            pre_dip_high = float(max(sli_h[:recross_at + 1]))
            pre_dip_mae = pre_dip_high - entry_px
            pre_dip_low = pre_dip_high  # naming abuse
    else:
        pre_dip_low = entry_px
        pre_dip_mae = 0.0

    # Snapshots after re-cross
    snapshots = {"recross_at": recross_at, "pre_dip_mae": pre_dip_mae}
    if recross_at >= 0:
        for T in ELAPSED_GRID:
            t_idx = recross_at + T
            # Censored — only track if trade still alive
            if t_idx > natural_exit or t_idx >= nbars:
                snapshots[f"breach_dist_T{T}"] = None
                snapshots[f"recov_pct_T{T}"] = None
                continue
            cur_close = sli_c[t_idx]
            if di == 1:
                breach_dist = cur_close - breach_level
                rec_pct = ((cur_close - pre_dip_low) / pre_dip_mae
                            if pre_dip_mae > 0 else 0.0)
            else:
                breach_dist = breach_level - cur_close
                rec_pct = ((pre_dip_low - cur_close) / pre_dip_mae
                            if pre_dip_mae > 0 else 0.0)
            snapshots[f"breach_dist_T{T}"] = float(breach_dist)
            snapshots[f"recov_pct_T{T}"] = float(rec_pct)

    return {
        "outcome": natural_outcome,
        "exit_idx_local": natural_exit,
        "max_mae": float(entry_px - min(sli_l[:natural_exit+1]))
                    if di == 1 else
                   float(max(sli_h[:natural_exit+1]) - entry_px),
        "max_mfe": float(max(sli_h[:natural_exit+1]) - entry_px)
                    if di == 1 else
                   float(entry_px - min(sli_l[:natural_exit+1])),
        "has_dipped": has_dipped,
        "pre_dip_low": pre_dip_low,
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
        ts_seconds = ts_close_1s.second.values.astype(np.int32)
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
            r = walk_post_recross(
                e, di, entry_px, float(tr["breach_level"]),
                float(tr["target"]), float(tr["stop"]),
                int(next_eod[e]), opens, highs, lows, closes,
                ts_seconds)
            if r is None: continue
            last_chain_exit = e + r["exit_idx_local"]
            if sessions[e] != "RTH":
                continue
            # Bucket
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
    df.to_parquet(OUT / "post_recross_recovery.parquet")
    print(f"\nTotal RTH trades: {len(df):,}")

    # Filter to trades where re-cross fired (and trade was alive)
    rc_df = df[df["recross_at"] >= 0].copy()
    print(f"Trades with re-cross fired: {len(rc_df):,} "
          f"({100*len(rc_df)/len(df):.1f}%)")

    print(f"\n  Per-bucket re-cross fire rate:")
    for grp in ("A_25pt", "B_14_15pt", "C_10_11pt"):
        g = df[df["group"] == grp]
        for bk in ("win_clean", "win_vshape",
                   "loss_runthenbreak", "loss_quick"):
            sub = g[g["bucket"] == bk]
            if len(sub) == 0: continue
            n_rc = (sub["recross_at"] >= 0).sum()
            print(f"    [{grp}] {bk}: {n_rc}/{len(sub)} = "
                  f"{100*n_rc/len(sub):.1f}%")

    # Pre-dip MAE distribution per bucket (Group A)
    print(f"\n{'='*78}")
    print(f"PRE-RE-CROSS DIP MAE — Group A (trades that re-crossed)")
    print(f"{'='*78}")
    g = rc_df[rc_df["group"] == "A_25pt"]
    print(f"  {'bucket':<22} {'n':>6} {'p25':>6} {'p50':>6} "
          f"{'p75':>6} {'p90':>6}")
    for bk in ("win_vshape", "loss_runthenbreak", "loss_quick"):
        sub = g[g["bucket"] == bk]
        if len(sub) == 0: continue
        v = sub["pre_dip_mae"].values
        print(f"  {bk:<22} {len(sub):>6,} "
              f"{np.percentile(v,25):>6.2f} "
              f"{np.percentile(v,50):>6.2f} "
              f"{np.percentile(v,75):>6.2f} "
              f"{np.percentile(v,90):>6.2f}")

    # ---- Breach distance after re-cross ----
    print(f"\n{'='*78}")
    print(f"BREACH DISTANCE AFTER RE-CROSS — close - breach (long; "
          f"signed)")
    print(f"  How far above breach is the price at T sec post re-cross?")
    print(f"{'='*78}")
    for grp in ("A_25pt", "B_14_15pt", "C_10_11pt"):
        g = rc_df[rc_df["group"] == grp]
        if len(g) == 0: continue
        print(f"\n[{grp}]")
        for T in ELAPSED_GRID:
            col = f"breach_dist_T{T}"
            print(f"\n  T={T}s post re-cross:  "
                  f"{'bucket':<22} {'n_alive':>8} "
                  f"{'p25':>6} {'p50':>6} {'p75':>6}")
            for bk in ("win_vshape", "loss_runthenbreak"):
                sub = g[(g["bucket"] == bk) & (g[col].notna())]
                if len(sub) == 0: continue
                v = sub[col].values
                print(f"                            "
                      f"{bk:<22} {len(sub):>8,} "
                      f"{np.percentile(v,25):>+6.2f} "
                      f"{np.percentile(v,50):>+6.2f} "
                      f"{np.percentile(v,75):>+6.2f}")

    # ---- Discriminator: % above breach by X pts at T ----
    print(f"\n{'='*78}")
    print(f"DISCRIMINATOR: % bucket with price >= breach + X at T post "
          f"re-cross")
    print(f"{'='*78}")
    for grp in ("A_25pt", "B_14_15pt", "C_10_11pt"):
        g = rc_df[rc_df["group"] == grp]
        if len(g) == 0: continue
        print(f"\n[{grp}]")
        print(f"  {'bucket':<22} {'T':>4} "
              f"{'>=L+0':>7} {'>=L+1':>7} {'>=L+2':>7} {'>=L+3':>7}")
        for bk in ("win_vshape", "loss_runthenbreak"):
            for T in (5, 10, 30, 60):
                col = f"breach_dist_T{T}"
                sub = g[(g["bucket"] == bk) & (g[col].notna())]
                if len(sub) == 0: continue
                v = sub[col].values
                line = f"  {bk:<22} {T:>4} "
                for thr in (0.0, 1.0, 2.0, 3.0):
                    pct = (v >= thr).mean() * 100
                    line += f"{pct:>5.1f}%  "
                print(line)
            print()

    print(f"\n[done] runtime: {time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()
