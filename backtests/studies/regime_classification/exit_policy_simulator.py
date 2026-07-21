"""Exit-policy simulator on hmm_4 state 3 + bar1-confirm + bar1-close cohort.

Path-shape diagnostic showed entries are valid (71% hit +1 ATR every year).
The regime-flip exit is what fails in 2023/2024. This sim tests 6 alternative
exit policies on the same NT-validated entry set:

  P0  baseline           regime-exit only (existing result)
  P1  partial_be         50% off at +1 ATR, runner stop BE, runner to regime
  P2  partial_trail      50% off at +1 ATR, runner trailing 1 ATR
  P3  full_pt_15         full exit at +1.5 ATR, else regime-exit
  P4  full_pt_20         full exit at +2.0 ATR, else regime-exit
  P5  time_stop_5m       exit at 5 min if regime hasn't flipped
  P6  recommended        partial_be + runner exits at +2 ATR OR after 10 min

Each trade is simulated on 1s bars from entry_ts to either regime exit
(or earlier policy-triggered exit). Stops fill at trigger price (no slip),
commission $5 RT applied post-sim to the final $ EV.

Goal: find a policy with positive year-by-year EV across all 4 OOS years
(stability matters more than peak).
"""
from __future__ import annotations
import os, sys, time
from pathlib import Path

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))
os.chdir(project_root)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import numpy as np
import pandas as pd
from numba import njit

NS = 1_000_000_000
PRODUCT = os.environ.get("PRODUCT", "NQ").upper()
NQ_MULT = 20.0
ES_MULT = 50.0
MULT = NQ_MULT if PRODUCT == "NQ" else ES_MULT
COMM = 5.0
OUT = Path("studies/regime_classification/results")
ONE_S = {y: f"data/raw/{PRODUCT}_v0_1s_{y}.parquet" for y in range(2019, 2026)}
ONE_S[2026] = f"data/raw/{PRODUCT}_v0_1s_2026_ytd.parquet"
IS_YEARS = (2020, 2021, 2022)
OOS_YEARS = (2023, 2024, 2025, 2026)


@njit
def sim_baseline(entry_ts, exit_ts, entry_px, exit_px,
                  dir_arr, atr_arr,
                  ts_1s, h_1s, l_1s, c_1s):
    n = len(entry_ts)
    out = np.full(n, np.nan)
    for k in range(n):
        if entry_ts[k] < 0 or exit_ts[k] <= entry_ts[k] or atr_arr[k] <= 0:
            continue
        out[k] = (exit_px[k] - entry_px[k]) * dir_arr[k] / atr_arr[k]
    return out


@njit
def sim_partial_be(entry_ts, exit_ts, entry_px, exit_px,
                    dir_arr, atr_arr,
                    ts_1s, h_1s, l_1s, c_1s):
    """50% off at +1 ATR (locks +0.5 ATR), runner BE stop, runner to regime."""
    n = len(entry_ts)
    out = np.full(n, np.nan)
    for k in range(n):
        T0 = entry_ts[k]; Tx = exit_ts[k]
        ep = entry_px[k]; xp = exit_px[k]
        d = dir_arr[k]; atr = atr_arr[k]
        if T0 < 0 or Tx <= T0 or atr <= 0:
            continue
        i_lo = np.searchsorted(ts_1s, T0, side="left")
        i_hi = np.searchsorted(ts_1s, Tx, side="left")
        if i_hi <= i_lo:
            continue
        t1 = ep + d * atr
        be = ep
        t1_fired = False
        be_fired = False
        for j in range(i_lo, i_hi):
            h = h_1s[j]; l = l_1s[j]
            if not t1_fired:
                if (d == 1 and h >= t1) or (d == -1 and l <= t1):
                    t1_fired = True
            else:
                if (d == 1 and l <= be) or (d == -1 and h >= be):
                    be_fired = True
                    break
        if not t1_fired:
            out[k] = (xp - ep) * d / atr
        elif be_fired:
            out[k] = 0.5 * 1.0 + 0.5 * 0.0
        else:
            out[k] = 0.5 * 1.0 + 0.5 * ((xp - ep) * d / atr)
    return out


@njit
def sim_partial_trail(entry_ts, exit_ts, entry_px, exit_px,
                       dir_arr, atr_arr,
                       ts_1s, h_1s, l_1s, c_1s, trail_atr):
    """50% off at +1 ATR, runner trailing `trail_atr` ATR from peak."""
    n = len(entry_ts)
    out = np.full(n, np.nan)
    for k in range(n):
        T0 = entry_ts[k]; Tx = exit_ts[k]
        ep = entry_px[k]; xp = exit_px[k]
        d = dir_arr[k]; atr = atr_arr[k]
        if T0 < 0 or Tx <= T0 or atr <= 0:
            continue
        i_lo = np.searchsorted(ts_1s, T0, side="left")
        i_hi = np.searchsorted(ts_1s, Tx, side="left")
        if i_hi <= i_lo:
            continue
        t1 = ep + d * atr
        trail_dist = trail_atr * atr
        t1_fired = False
        running_ext = ep
        runner_exit_px = np.nan
        for j in range(i_lo, i_hi):
            h = h_1s[j]; l = l_1s[j]
            if not t1_fired:
                if d == 1 and h >= t1:
                    t1_fired = True
                    running_ext = max(h, t1)
                elif d == -1 and l <= t1:
                    t1_fired = True
                    running_ext = min(l, t1)
            else:
                if d == 1:
                    if h > running_ext:
                        running_ext = h
                    trail_stop = running_ext - trail_dist
                    if l <= trail_stop:
                        runner_exit_px = trail_stop
                        break
                else:
                    if l < running_ext:
                        running_ext = l
                    trail_stop = running_ext + trail_dist
                    if h >= trail_stop:
                        runner_exit_px = trail_stop
                        break
        if not t1_fired:
            out[k] = (xp - ep) * d / atr
        elif not np.isnan(runner_exit_px):
            out[k] = 0.5 * 1.0 + 0.5 * ((runner_exit_px - ep) * d / atr)
        else:
            out[k] = 0.5 * 1.0 + 0.5 * ((xp - ep) * d / atr)
    return out


@njit
def sim_full_pt(entry_ts, exit_ts, entry_px, exit_px,
                 dir_arr, atr_arr,
                 ts_1s, h_1s, l_1s, c_1s, pt_atr):
    """Full exit at +`pt_atr` ATR, else regime-exit."""
    n = len(entry_ts)
    out = np.full(n, np.nan)
    for k in range(n):
        T0 = entry_ts[k]; Tx = exit_ts[k]
        ep = entry_px[k]; xp = exit_px[k]
        d = dir_arr[k]; atr = atr_arr[k]
        if T0 < 0 or Tx <= T0 or atr <= 0:
            continue
        i_lo = np.searchsorted(ts_1s, T0, side="left")
        i_hi = np.searchsorted(ts_1s, Tx, side="left")
        if i_hi <= i_lo:
            continue
        pt = ep + d * pt_atr * atr
        pt_hit = False
        for j in range(i_lo, i_hi):
            h = h_1s[j]; l = l_1s[j]
            if (d == 1 and h >= pt) or (d == -1 and l <= pt):
                pt_hit = True
                break
        if pt_hit:
            out[k] = pt_atr
        else:
            out[k] = (xp - ep) * d / atr
    return out


@njit
def sim_time_stop(entry_ts, exit_ts, entry_px, exit_px,
                   dir_arr, atr_arr,
                   ts_1s, h_1s, l_1s, c_1s, time_stop_min):
    """Exit at `time_stop_min` min if regime hasn't flipped (close at that bar)."""
    n = len(entry_ts)
    out = np.full(n, np.nan)
    for k in range(n):
        T0 = entry_ts[k]; Tx = exit_ts[k]
        ep = entry_px[k]; xp = exit_px[k]
        d = dir_arr[k]; atr = atr_arr[k]
        if T0 < 0 or Tx <= T0 or atr <= 0:
            continue
        time_stop_ts = T0 + time_stop_min * 60 * NS
        if Tx <= time_stop_ts:
            out[k] = (xp - ep) * d / atr
        else:
            i = np.searchsorted(ts_1s, time_stop_ts, side="left")
            if i < len(ts_1s):
                stop_px = c_1s[i]
                out[k] = (stop_px - ep) * d / atr
            else:
                out[k] = (xp - ep) * d / atr
    return out


@njit
def sim_recommended(entry_ts, exit_ts, entry_px, exit_px,
                     dir_arr, atr_arr,
                     ts_1s, h_1s, l_1s, c_1s,
                     runner_pt_atr, time_stop_min):
    """50% off at +1, runner stop BE, runner exits at +runner_pt_atr OR time stop."""
    n = len(entry_ts)
    out = np.full(n, np.nan)
    for k in range(n):
        T0 = entry_ts[k]; Tx = exit_ts[k]
        ep = entry_px[k]; xp = exit_px[k]
        d = dir_arr[k]; atr = atr_arr[k]
        if T0 < 0 or Tx <= T0 or atr <= 0:
            continue
        time_stop_ts = T0 + time_stop_min * 60 * NS
        end_ts = min(Tx, time_stop_ts)
        i_lo = np.searchsorted(ts_1s, T0, side="left")
        i_hi = np.searchsorted(ts_1s, end_ts, side="left")
        if i_hi <= i_lo:
            continue
        t1 = ep + d * atr
        runner_pt = ep + d * runner_pt_atr * atr
        be = ep
        t1_fired = False
        be_fired = False
        runner_pt_fired = False
        for j in range(i_lo, i_hi):
            h = h_1s[j]; l = l_1s[j]
            if not t1_fired:
                if (d == 1 and h >= t1) or (d == -1 and l <= t1):
                    t1_fired = True
            else:
                if (d == 1 and h >= runner_pt) or (d == -1 and l <= runner_pt):
                    runner_pt_fired = True
                    break
                if (d == 1 and l <= be) or (d == -1 and h >= be):
                    be_fired = True
                    break
        if not t1_fired:
            # Exit at end_ts close
            if end_ts == Tx:
                out[k] = (xp - ep) * d / atr
            else:
                i = np.searchsorted(ts_1s, end_ts, side="left")
                if i < len(ts_1s):
                    stop_px = c_1s[i]
                    out[k] = (stop_px - ep) * d / atr
                else:
                    out[k] = (xp - ep) * d / atr
        elif runner_pt_fired:
            out[k] = 0.5 * 1.0 + 0.5 * runner_pt_atr
        elif be_fired:
            out[k] = 0.5 * 1.0 + 0.5 * 0.0
        else:
            # Runner held to end_ts
            if end_ts == Tx:
                runner_pnl = (xp - ep) * d / atr
            else:
                i = np.searchsorted(ts_1s, end_ts, side="left")
                if i < len(ts_1s):
                    runner_pnl = (c_1s[i] - ep) * d / atr
                else:
                    runner_pnl = (xp - ep) * d / atr
            out[k] = 0.5 * 1.0 + 0.5 * runner_pnl
    return out


def annotate_policies(df):
    parts = []
    for y in sorted(df["year"].unique()):
        sub_idx = df.index[df["year"] == y]
        parts_bars = []
        for yy in (y - 1, y, y + 1):
            p = ONE_S.get(yy)
            if p and Path(p).exists():
                parts_bars.append(pd.read_parquet(
                    p, columns=["high", "low", "close"]))
        bars = pd.concat(parts_bars).sort_index()
        bars = bars[~bars.index.duplicated(keep="first")]
        if bars.index.tz is None:
            bars.index = bars.index.tz_localize("UTC")
        ts_1s = bars.index.values.astype(np.int64)
        h_1s = bars["high"].to_numpy(np.float64)
        l_1s = bars["low"].to_numpy(np.float64)
        c_1s = bars["close"].to_numpy(np.float64)
        sub = df.loc[sub_idx]
        e_ts = sub["entry_ts"].to_numpy(np.int64)
        x_ts = sub["exit_ts"].to_numpy(np.int64)
        e_px = sub["entry_px"].to_numpy(np.float64)
        x_px = sub["exit_px"].to_numpy(np.float64)
        drs  = sub["signal_direction"].to_numpy(np.int64)
        ats  = sub["entry_atr"].to_numpy(np.float64)

        p0 = sim_baseline       (e_ts, x_ts, e_px, x_px, drs, ats, ts_1s, h_1s, l_1s, c_1s)
        p1 = sim_partial_be     (e_ts, x_ts, e_px, x_px, drs, ats, ts_1s, h_1s, l_1s, c_1s)
        p2 = sim_partial_trail  (e_ts, x_ts, e_px, x_px, drs, ats, ts_1s, h_1s, l_1s, c_1s, 1.0)
        p3 = sim_full_pt        (e_ts, x_ts, e_px, x_px, drs, ats, ts_1s, h_1s, l_1s, c_1s, 1.5)
        p4 = sim_full_pt        (e_ts, x_ts, e_px, x_px, drs, ats, ts_1s, h_1s, l_1s, c_1s, 2.0)
        p5 = sim_time_stop      (e_ts, x_ts, e_px, x_px, drs, ats, ts_1s, h_1s, l_1s, c_1s, 5)
        p6 = sim_recommended    (e_ts, x_ts, e_px, x_px, drs, ats, ts_1s, h_1s, l_1s, c_1s, 2.0, 10)

        addl = pd.DataFrame({
            "p0_baseline": p0,
            "p1_partial_be": p1,
            "p2_partial_trail1": p2,
            "p3_full_pt15": p3,
            "p4_full_pt20": p4,
            "p5_time_stop5m": p5,
            "p6_recommended": p6,
        }, index=sub_idx)
        parts.append(addl)
        print(f"  {y}: {len(sub):,} trades simulated")
    return pd.concat(parts)


def report_policy(df, policy_col, label):
    print(f"\n  {label}")
    print(f"  {'year':<6}{'n':>6}{'win%':>8}{'meanATR':>10}{'medATR':>10}"
          f"{'$/tr':>10}{'std ATR':>10}")
    for y in OOS_YEARS:
        sub = df[df["year"] == y].dropna(subset=[policy_col])
        if len(sub) == 0:
            continue
        wr = (sub[policy_col] > 0).mean()
        ma = sub[policy_col].mean()
        med = sub[policy_col].median()
        atr_avg = sub["entry_atr"].mean()
        dol = ma * atr_avg * MULT - COMM
        sd = sub[policy_col].std()
        print(f"  {y:<6}{len(sub):>6}{wr:>7.1%}"
              f"{ma:>+10.3f}{med:>+10.3f}{dol:>+10.2f}{sd:>+10.3f}")
    # Pooled OOS
    sub_oos = df[df["year"].isin(OOS_YEARS)].dropna(subset=[policy_col])
    if len(sub_oos):
        wr = (sub_oos[policy_col] > 0).mean()
        ma = sub_oos[policy_col].mean()
        med = sub_oos[policy_col].median()
        atr_avg = sub_oos["entry_atr"].mean()
        dol = ma * atr_avg * MULT - COMM
        sd = sub_oos[policy_col].std()
        print(f"  {'POOL':<6}{len(sub_oos):>6}{wr:>7.1%}"
              f"{ma:>+10.3f}{med:>+10.3f}{dol:>+10.2f}{sd:>+10.3f}")


def main():
    t0 = time.time()
    p = OUT / f"path_shape_{PRODUCT.lower()}.parquet"
    df = pd.read_parquet(p).reset_index(drop=True)
    df["entry_ts"] = df["entry_ts"].astype(np.int64)
    df["exit_ts"]  = df["exit_ts"].astype(np.int64)
    df["signal_direction"] = df["signal_direction"].astype(np.int64)
    print(f"Loaded {len(df):,} trades from {p.name}")

    print("Simulating policies (1s walk per trade) ...")
    addl = annotate_policies(df)
    df = pd.concat([df, addl], axis=1)

    out_p = OUT / f"exit_policies_{PRODUCT.lower()}.parquet"
    df.to_parquet(out_p, index=False)
    print(f"  saved {out_p}")

    print(f"\n{'='*78}\n EXIT POLICIES BY YEAR  ($/tr is net of $5 RT commission)\n{'='*78}")
    report_policy(df, "p0_baseline",       "P0  BASELINE  (regime-exit only)")
    report_policy(df, "p1_partial_be",     "P1  PARTIAL+BE  (50% at +1, runner BE → regime)")
    report_policy(df, "p2_partial_trail1", "P2  PARTIAL+TRAIL  (50% at +1, runner trail 1ATR)")
    report_policy(df, "p3_full_pt15",      "P3  FULL_PT 1.5  (exit at +1.5 ATR else regime)")
    report_policy(df, "p4_full_pt20",      "P4  FULL_PT 2.0  (exit at +2.0 ATR else regime)")
    report_policy(df, "p5_time_stop5m",    "P5  TIME_STOP 5m (exit at 5 min if no flip)")
    report_policy(df, "p6_recommended",    "P6  RECOMMENDED  (50% at +1 + BE + runner +2 OR 10min)")

    # Summary: pooled OOS comparison
    print(f"\n{'='*78}\n SUMMARY — pooled OOS  (4 years)\n{'='*78}")
    print(f"  {'policy':<26}{'n':>6}{'win%':>8}{'meanATR':>10}{'$/tr':>10}"
          f"{'std ATR':>10}{'yr+/4':>10}")
    pols = [("p0_baseline", "P0 baseline"),
             ("p1_partial_be", "P1 partial+BE"),
             ("p2_partial_trail1", "P2 partial+trail1"),
             ("p3_full_pt15", "P3 full PT 1.5"),
             ("p4_full_pt20", "P4 full PT 2.0"),
             ("p5_time_stop5m", "P5 time 5m"),
             ("p6_recommended", "P6 recommended")]
    for col, label in pols:
        sub_oos = df[df["year"].isin(OOS_YEARS)].dropna(subset=[col])
        if not len(sub_oos):
            continue
        wr = (sub_oos[col] > 0).mean()
        ma = sub_oos[col].mean()
        atr_avg = sub_oos["entry_atr"].mean()
        dol = ma * atr_avg * MULT - COMM
        sd = sub_oos[col].std()
        # Year-positive count
        yp = 0
        for y in OOS_YEARS:
            yg = df[df["year"] == y].dropna(subset=[col])
            if len(yg) == 0:
                continue
            y_dol = yg[col].mean() * yg["entry_atr"].mean() * MULT - COMM
            if y_dol > 0:
                yp += 1
        print(f"  {label:<26}{len(sub_oos):>6}{wr:>7.1%}{ma:>+10.3f}"
              f"{dol:>+10.2f}{sd:>+10.3f}{yp:>9}/4")

    print(f"\n[done] {(time.time()-t0)/60:.1f} min")


if __name__ == "__main__":
    main()
