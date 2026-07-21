"""Per-bucket 1s path characterization for breakout-filter trades (RTH).

For each trade, walk the 1s path from entry (first 1s after 1m trigger
close) to PT / prior-level SL / EOD. Compute time-series of MFE & MAE
at every second.

Bucket assignment (at 1s precision):
  win_clean         : outcome=win, MAE-before-first-MFE-2.5 < 2.0 pts
  win_vshape        : outcome=win, MAE-before-first-MFE-2.5 >= 2.0 pts
  loss_runthenbreak : outcome=loss (prior-level SL), max MFE >= 2.5 pts
  loss_quick        : outcome=loss (prior-level SL), max MFE < 2.5 pts

For each bucket per gap-group, report:
  (a) MFE & MAE distribution at FIXED time points (5, 10, 30, 60s)
  (b) Time-to-first-cross distribution for MFE [1, 2, 3, 5] pts
  (c) Time-to-first-cross distribution for MAE [1, 2, 3, 5] pts
  (d) Time-to-peak-MFE, time-to-peak-MAE, time-to-exit

Goal: identify a real-time discriminator that separates clean winners
from v-shape winners and from losers (especially RtB losers).
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

NQ_DOLLAR_PER_PT = 20.0
COMMISSION_PTS = 0.25

ARM_THRESHOLD = 2.5
CLEAN_MAE_CAP = 2.0
TIME_POINTS = [5, 10, 15, 30, 60, 120, 300]  # seconds since entry
MFE_CROSS_PTS = [0.5, 1.0, 2.0, 3.0, 5.0, 7.5, 10.0]
MAE_CROSS_PTS = [0.5, 1.0, 2.0, 3.0, 5.0, 7.5, 10.0]


def simulate_path_1s(entry_idx, di, entry_px, target, prior_sl, eod_idx,
                     highs, lows, closes):
    """Walk 1s path from entry to PT/prior-SL/EOD. Return per-second
    MFE/MAE arrays plus exit info."""
    n = len(highs)
    last = min(eod_idx, n - 1)
    if entry_idx >= n or last < entry_idx:
        return None
    sli_h = highs[entry_idx : last + 1]
    sli_l = lows[entry_idx : last + 1]
    sli_c = closes[entry_idx : last + 1]
    nbars = len(sli_h)

    if di == 1:
        running_mfe = np.maximum.accumulate(sli_h - entry_px)
        running_mae = np.maximum.accumulate(entry_px - sli_l)
        sl_hit = sli_l <= prior_sl
        tgt_hit = sli_h >= target
    else:
        running_mfe = np.maximum.accumulate(entry_px - sli_l)
        running_mae = np.maximum.accumulate(sli_h - entry_px)
        sl_hit = sli_h >= prior_sl
        tgt_hit = sli_l <= target

    sl_idx = int(np.argmax(sl_hit)) if sl_hit.any() else nbars
    tgt_idx = int(np.argmax(tgt_hit)) if tgt_hit.any() else nbars

    if sl_idx == nbars and tgt_idx == nbars:
        outcome = "eod_flat"; exit_idx = nbars - 1
        exit_px = float(sli_c[-1])
    elif sl_idx <= tgt_idx:
        outcome = "loss"; exit_idx = sl_idx; exit_px = float(prior_sl)
    else:
        outcome = "win"; exit_idx = tgt_idx; exit_px = float(target)

    pnl_pts = (exit_px - entry_px) * di
    return {
        "outcome": outcome,
        "exit_idx_in_slice": exit_idx,
        "exit_idx_global": entry_idx + exit_idx,
        "exit_px": exit_px,
        "pnl_pts": float(pnl_pts),
        "pnl_net_pts": float(pnl_pts - COMMISSION_PTS),
        "mfe_t": running_mfe[: exit_idx + 1],
        "mae_t": running_mae[: exit_idx + 1],
        "max_mfe": float(running_mfe[exit_idx]),
        "max_mae": float(running_mae[exit_idx]),
        "duration_s": int(exit_idx),
    }


def first_cross_idx(arr: np.ndarray, threshold: float) -> int:
    """First idx where arr >= threshold, or -1 if never."""
    mask = arr >= threshold
    return int(np.argmax(mask)) if mask.any() else -1


def assign_bucket(outcome: str, mfe_t: np.ndarray, mae_t: np.ndarray,
                  max_mfe: float) -> str:
    if outcome == "win":
        t_arm = first_cross_idx(mfe_t, ARM_THRESHOLD)
        if t_arm < 0:
            # PT reached without ever crossing ARM (e.g. PT < ARM)
            return "win_no_arm"
        # MAE during [0, t_arm)
        mae_before = float(mae_t[:t_arm].max()) if t_arm > 0 else 0.0
        return "win_clean" if mae_before < CLEAN_MAE_CAP else "win_vshape"
    elif outcome == "loss":
        return ("loss_runthenbreak" if max_mfe >= ARM_THRESHOLD
                else "loss_quick")
    else:
        return "timed_out"


def main():
    t0 = time.time()
    all_paths = []

    for year in (2024, 2025):
        print(f"\n[{year}] loading 1s + 1m + triggers...")
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
        print(f"  triggers: {len(triggers):,}")

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
        skipped_chain = 0
        for tr in triggers:
            ts = pd.Timestamp(tr["bar_ts_close"])
            if ts.tz is None:
                ts = ts.tz_localize("UTC")
            else:
                ts = ts.tz_convert("UTC")
            e = map_1m_trigger_to_1s_entry(ts, ts_close_1s)
            if e < 0: continue
            if e <= last_chain_exit:
                skipped_chain += 1; continue
            di = tr["direction"]
            entry_px = float(opens[e])
            r = simulate_path_1s(
                e, di, entry_px, float(tr["target"]),
                float(tr["stop"]), int(next_eod[e]),
                highs, lows, closes)
            if r is None: continue
            last_chain_exit = r["exit_idx_global"]
            if sessions[e] != "RTH":
                continue
            bucket = assign_bucket(
                r["outcome"], r["mfe_t"], r["mae_t"], r["max_mfe"])
            all_paths.append({
                "year": year,
                "level_pair": tr["level_pair"],
                "group": assign_group(tr["level_pair"]),
                "direction": di,
                "outcome": r["outcome"],
                "bucket": bucket,
                "max_mfe": r["max_mfe"],
                "max_mae": r["max_mae"],
                "duration_s": r["duration_s"],
                "pnl_dollars": r["pnl_net_pts"] * NQ_DOLLAR_PER_PT,
                # Per-time-point MFE/MAE
                **{f"mfe_at_T{T}":
                   float(r["mfe_t"][min(T, len(r["mfe_t"]) - 1)])
                   for T in TIME_POINTS},
                **{f"mae_at_T{T}":
                   float(r["mae_t"][min(T, len(r["mae_t"]) - 1)])
                   for T in TIME_POINTS},
                # First-cross times for MFE
                **{f"t_mfe_{th}": first_cross_idx(r["mfe_t"], th)
                   for th in MFE_CROSS_PTS},
                # First-cross times for MAE
                **{f"t_mae_{th}": first_cross_idx(r["mae_t"], th)
                   for th in MAE_CROSS_PTS},
                # Time of peak
                "t_peak_mfe": int(np.argmax(r["mfe_t"])),
                "t_peak_mae": int(np.argmax(r["mae_t"])),
            })

    df = pd.DataFrame(all_paths)
    df.to_parquet(OUT / "rth_path_chars.parquet")
    print(f"\nTotal RTH paths: {len(df):,}  "
          f"(saved to rth_path_chars.parquet)")
    print(f"  runtime: {time.time()-t0:.1f}s")

    # ---- Bucket counts per group ----
    print(f"\n{'='*78}\n"
          f"BUCKET COUNTS per group (RTH 2024+2025, 1s precision)\n"
          f"{'='*78}")
    for grp in ("A_25pt", "B_14_15pt", "C_10_11pt"):
        g = df[df["group"] == grp]
        print(f"\n[{grp}] n={len(g):,}")
        for bk in ("win_clean", "win_vshape", "win_no_arm",
                   "loss_runthenbreak", "loss_quick", "timed_out"):
            sub = g[g["bucket"] == bk]
            if len(sub) == 0: continue
            print(f"  {bk:<20} n={len(sub):>5,} "
                  f"({100*len(sub)/len(g):>4.1f}%) "
                  f"mean ${sub['pnl_dollars'].mean():>+7.2f}/tr  "
                  f"total ${sub['pnl_dollars'].sum():>+10,.0f}")

    # ---- (a) MFE/MAE distribution at fixed time points ----
    print(f"\n{'='*78}\n"
          f"PATH SHAPE — MFE / MAE at fixed time points "
          f"(p25 / p50 / p75)\n"
          f"{'='*78}")
    for grp in ("A_25pt", "B_14_15pt", "C_10_11pt"):
        g = df[df["group"] == grp]
        print(f"\n[{grp}]")
        for bk in ("win_clean", "win_vshape",
                   "loss_runthenbreak", "loss_quick"):
            sub = g[g["bucket"] == bk]
            if len(sub) == 0: continue
            print(f"\n  [{bk}] n={len(sub):,}")
            print(f"  {'T':>4}  {'MFE_p25':>8} {'MFE_p50':>8} "
                  f"{'MFE_p75':>8}  |  {'MAE_p25':>8} {'MAE_p50':>8} "
                  f"{'MAE_p75':>8}")
            for T in TIME_POINTS:
                mfe_col = f"mfe_at_T{T}"
                mae_col = f"mae_at_T{T}"
                # Censor: only trades alive at T
                alive = sub[sub["duration_s"] >= T]
                if len(alive) == 0:
                    continue
                mfe = alive[mfe_col].values
                mae = alive[mae_col].values
                print(f"  {T:>4}  "
                      f"{np.percentile(mfe,25):>8.2f} "
                      f"{np.percentile(mfe,50):>8.2f} "
                      f"{np.percentile(mfe,75):>8.2f}  |  "
                      f"{np.percentile(mae,25):>8.2f} "
                      f"{np.percentile(mae,50):>8.2f} "
                      f"{np.percentile(mae,75):>8.2f}  "
                      f"(n_alive={len(alive):,})")

    # ---- (b) Time to first MFE cross ----
    print(f"\n{'='*78}\n"
          f"TIME TO FIRST MFE CROSS (median seconds, then "
          f"% of bucket that ever crosses)\n"
          f"{'='*78}")
    for grp in ("A_25pt", "B_14_15pt", "C_10_11pt"):
        g = df[df["group"] == grp]
        print(f"\n[{grp}]")
        # Header
        hdr = "  bucket             "
        for th in MFE_CROSS_PTS:
            hdr += f"  +{th:>5}pt  "
        print(hdr)
        for bk in ("win_clean", "win_vshape",
                   "loss_runthenbreak", "loss_quick"):
            sub = g[g["bucket"] == bk]
            if len(sub) == 0: continue
            row = f"  {bk:<20}"
            for th in MFE_CROSS_PTS:
                col = f"t_mfe_{th}"
                vals = sub[col].values
                crossed = vals[vals >= 0]
                if len(crossed) == 0:
                    row += f"   never    "
                else:
                    pct = 100 * len(crossed) / len(sub)
                    med = np.median(crossed)
                    row += f"  {med:>4.0f}s ({pct:>3.0f}%)"
            print(row)

    # ---- (c) Time to first MAE cross ----
    print(f"\n{'='*78}\n"
          f"TIME TO FIRST MAE CROSS (median seconds, then "
          f"% of bucket that ever crosses)\n"
          f"{'='*78}")
    for grp in ("A_25pt", "B_14_15pt", "C_10_11pt"):
        g = df[df["group"] == grp]
        print(f"\n[{grp}]")
        hdr = "  bucket             "
        for th in MAE_CROSS_PTS:
            hdr += f"  -{th:>5}pt  "
        print(hdr)
        for bk in ("win_clean", "win_vshape",
                   "loss_runthenbreak", "loss_quick"):
            sub = g[g["bucket"] == bk]
            if len(sub) == 0: continue
            row = f"  {bk:<20}"
            for th in MAE_CROSS_PTS:
                col = f"t_mae_{th}"
                vals = sub[col].values
                crossed = vals[vals >= 0]
                if len(crossed) == 0:
                    row += f"   never    "
                else:
                    pct = 100 * len(crossed) / len(sub)
                    med = np.median(crossed)
                    row += f"  {med:>4.0f}s ({pct:>3.0f}%)"
            print(row)

    # ---- (d) Peak / exit timing ----
    print(f"\n{'='*78}\n"
          f"PEAK / EXIT TIMING per bucket (median seconds)\n"
          f"{'='*78}")
    for grp in ("A_25pt", "B_14_15pt", "C_10_11pt"):
        g = df[df["group"] == grp]
        print(f"\n[{grp}]")
        print(f"  {'bucket':<20} {'n':>6} "
              f"{'t_peak_mfe':>10} {'t_peak_mae':>10} "
              f"{'duration':>10}")
        for bk in ("win_clean", "win_vshape",
                   "loss_runthenbreak", "loss_quick"):
            sub = g[g["bucket"] == bk]
            if len(sub) == 0: continue
            print(f"  {bk:<20} {len(sub):>6,} "
                  f"{int(sub['t_peak_mfe'].median()):>10,} "
                  f"{int(sub['t_peak_mae'].median()):>10,} "
                  f"{int(sub['duration_s'].median()):>10,}")


if __name__ == "__main__":
    main()
