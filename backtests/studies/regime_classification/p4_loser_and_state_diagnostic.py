"""P4 follow-up — TWO related diagnostics.

PART A — Regime-exit loser path shape per year (NT P4 results).
  For trades that did NOT hit +2 ATR PT (exit_reason == 'regime_flip'),
  compute MFE / MAE / time-to-peak from 1s bars. Split by year. Asks:
    "When state 3 fails to deliver +2 ATR, does it still reach a
     tradable amount (+0.5 / +1.0 / +1.5) before the regime flips back?"
  If yes → entries are valid; loss management / earlier exits could help.
  If no  → entries are weaker in those years; the state captures less.

PART B — State 3 character: 2024 vs 2025.
  Using the offline-classified 1m bars in state==3, compare:
    - all 24 state features (mean / median)
    - state-3 run length (consecutive bar count) distribution
    - transition probabilities (where does state 3 go next?)
    - total minutes / day in state 3
  Asks:
    "Is 'state 3' in 2024 the SAME phenomenon as 'state 3' in 2025,
     or different distributions wearing the same label?"
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
OUT = Path("studies/regime_classification/results")
ONE_S = {y: f"data/raw/{PRODUCT}_v0_1s_{y}.parquet" for y in range(2019, 2026)}
ONE_S[2026] = f"data/raw/{PRODUCT}_v0_1s_2026_ytd.parquet"
NT_TRADES = "backtests/hmm_state_filtered/results/nq_hmm_4_s3_pt2p0_{}/trades.parquet"

STATE_COL = "hmm_4"
TARGET_STATE = 3
IS_YEARS = (2020, 2021, 2022)
OOS_YEARS = (2023, 2024, 2025, 2026)

FEATURE_COLS = [
    "ret_5s", "ret_30s", "ret_60s", "ret_300s", "cum_abs_60s",
    "rv_30s", "rv_300s",
    "range_atr_60s", "range_atr_300s", "range_atr_1800s",
    "vol_expansion",
    "efficiency_300s", "chop_ratio_300s", "n_dir_changes_60s",
    "body_ratio", "upper_wick", "lower_wick", "close_location",
    "vwap_z_signed", "vwap_z_abs", "vwap_slope_5m_atr", "session_pos",
    "range_pct_60s_vs_1h", "compress_drift",
]


# ───────────────────────────── PART A ───────────────────────────────

@njit
def compute_path(entry_ts, exit_ts, entry_px, dir_arr, atr_arr,
                  ts_1s, h_1s, l_1s):
    n = len(entry_ts)
    mfe = np.full(n, np.nan)
    mae = np.full(n, np.nan)
    t_peak = np.full(n, -1, dtype=np.int64)
    for k in range(n):
        T0 = entry_ts[k]; T1 = exit_ts[k]
        if T0 < 0 or T1 <= T0 or atr_arr[k] <= 0:
            continue
        i_lo = np.searchsorted(ts_1s, T0, side="left")
        i_hi = np.searchsorted(ts_1s, T1, side="left")
        if i_hi <= i_lo:
            continue
        ep = entry_px[k]; d = dir_arr[k]; atr = atr_arr[k]
        running_max_mfe = 0.0
        running_min_mae = 0.0
        running_peak_ts = -1
        for j in range(i_lo, i_hi):
            h = h_1s[j]; l = l_1s[j]
            if d == 1:
                this_mfe = h - ep
                this_mae = ep - l
            else:
                this_mfe = ep - l
                this_mae = h - ep
            if this_mfe > running_max_mfe:
                running_max_mfe = this_mfe
                running_peak_ts = ts_1s[j]
            if this_mae > running_min_mae:
                running_min_mae = this_mae
        mfe[k] = max(running_max_mfe, 0.0) / atr
        mae[k] = max(running_min_mae, 0.0) / atr
        if running_peak_ts > 0:
            t_peak[k] = running_peak_ts
    return mfe, mae, t_peak


def annotate_loser_paths(losers):
    parts = []
    for y in sorted(losers["year"].unique()):
        sub_idx = losers.index[losers["year"] == y]
        bars_parts = []
        for yy in (y - 1, y, y + 1):
            p = ONE_S.get(yy)
            if p and Path(p).exists():
                bars_parts.append(pd.read_parquet(p, columns=["high", "low"]))
        bars = pd.concat(bars_parts).sort_index()
        bars = bars[~bars.index.duplicated(keep="first")]
        if bars.index.tz is None:
            bars.index = bars.index.tz_localize("UTC")
        ts_1s = bars.index.values.astype(np.int64)
        h_1s = bars["high"].to_numpy(np.float64)
        l_1s = bars["low"].to_numpy(np.float64)
        sub = losers.loc[sub_idx]
        mfe, mae, tp = compute_path(
            sub["entry_ts"].to_numpy(np.int64),
            sub["exit_ts"].to_numpy(np.int64),
            sub["entry_px"].to_numpy(np.float64),
            sub["signal_direction"].to_numpy(np.int64),
            sub["entry_atr"].to_numpy(np.float64),
            ts_1s, h_1s, l_1s)
        addl = pd.DataFrame({
            "mfe_atr": mfe, "mae_atr": mae,
            "peak_ts": tp}, index=sub_idx)
        parts.append(addl)
    return pd.concat(parts)


def report_part_a(trades):
    print(f"\n{'='*92}")
    print("PART A — REGIME-EXIT LOSERS  (trades that didn't hit +2 ATR PT)")
    print(f"{'='*92}")
    losers = trades[trades["exit_reason"] == "regime_flip"].copy()
    print(f"  total regime-flip exits (all years): {len(losers):,}")

    losers = annotate_loser_paths(losers)
    losers = trades[trades["exit_reason"] == "regime_flip"].join(losers, how="inner")
    losers["hold_min"] = (losers["exit_ts"] - losers["entry_ts"]) / (60 * NS)
    losers["time_to_peak_min"] = np.where(
        losers["peak_ts"] > 0,
        (losers["peak_ts"] - losers["entry_ts"]) / (60 * NS),
        np.nan)

    print(f"\n  Per-year — among regime-exit losers, how far did MFE reach?")
    print(f"  {'year':<6}{'n':>6}{'%>=0.25':>9}{'%>=0.5':>9}{'%>=1.0':>9}"
          f"{'%>=1.5':>9}{'%>=2.0':>9}{'medMFE':>9}{'medMAE':>9}"
          f"{'medPeak':>10}{'medHold':>10}")
    for y in (2020, 2021, 2022, 2023, 2024, 2025, 2026):
        g = losers[losers["year"] == y]
        if len(g) < 5:
            continue
        tag = "IS" if y in IS_YEARS else ""
        print(f"  {y:<6}{len(g):>6}"
              f"{(g['mfe_atr']>=0.25).mean():>8.1%}"
              f"{(g['mfe_atr']>=0.5).mean():>8.1%}"
              f"{(g['mfe_atr']>=1.0).mean():>8.1%}"
              f"{(g['mfe_atr']>=1.5).mean():>8.1%}"
              f"{(g['mfe_atr']>=2.0).mean():>8.1%}"
              f"{g['mfe_atr'].median():>+9.3f}"
              f"{g['mae_atr'].median():>+9.3f}"
              f"{g['time_to_peak_min'].median():>9.1f}m"
              f"{g['hold_min'].median():>9.1f}m"
              f"  {tag}")

    # MFE distribution percentiles per year for losers
    print(f"\n  MFE percentiles per year (regime-exit losers, ATR units)")
    print(f"  {'year':<6}{'25%':>8}{'50%':>8}{'75%':>8}{'90%':>8}{'95%':>8}{'99%':>8}")
    for y in (2020, 2021, 2022, 2023, 2024, 2025, 2026):
        g = losers[losers["year"] == y]
        if len(g) < 10:
            continue
        m = g["mfe_atr"]
        print(f"  {y:<6}{m.quantile(0.25):>+8.3f}{m.quantile(0.5):>+8.3f}"
              f"{m.quantile(0.75):>+8.3f}{m.quantile(0.9):>+8.3f}"
              f"{m.quantile(0.95):>+8.3f}{m.quantile(0.99):>+8.3f}")

    return losers


# ───────────────────────────── PART B ───────────────────────────────

def report_part_b():
    print(f"\n{'='*92}")
    print(f"PART B — STATE 3 CHARACTER: 2024 vs 2025  (and all years for context)")
    print(f"{'='*92}")
    states = pd.read_parquet(OUT / f"states_{PRODUCT.lower()}_1m.parquet")
    s3 = states[states[STATE_COL] == TARGET_STATE].copy()
    print(f"  Total state-3 bars: {len(s3):,}")

    print(f"\n  Bars in state 3 per year (= minutes of state-3 per year):")
    print(f"  {'year':<6}{'bars':>9}{'% of year':>11}")
    for y in (2020, 2021, 2022, 2023, 2024, 2025, 2026):
        n_yr = len(states[states["year"] == y])
        n_s3 = len(s3[s3["year"] == y])
        if n_yr == 0:
            continue
        print(f"  {y:<6}{n_s3:>9,}{n_s3/n_yr:>10.1%}")

    # State-3 run-length distribution per year
    print(f"\n  State-3 run-length (consecutive 1m bars in state 3) per year:")
    state_arr = states[STATE_COL].to_numpy(np.int64)
    state_yr = states["year"].to_numpy(np.int64)
    runs_by_year = {y: [] for y in (2020, 2021, 2022, 2023, 2024, 2025, 2026)}
    cur_run = 0
    cur_run_year = 0
    for i in range(len(state_arr)):
        if state_arr[i] == TARGET_STATE:
            if cur_run == 0:
                cur_run_year = state_yr[i]
            cur_run += 1
        else:
            if cur_run > 0:
                if cur_run_year in runs_by_year:
                    runs_by_year[cur_run_year].append(cur_run)
                cur_run = 0
    if cur_run > 0 and cur_run_year in runs_by_year:
        runs_by_year[cur_run_year].append(cur_run)

    print(f"  {'year':<6}{'n runs':>8}{'mean':>8}{'med':>8}{'p75':>8}"
          f"{'p90':>8}{'p95':>8}{'max':>8}")
    for y in (2020, 2021, 2022, 2023, 2024, 2025, 2026):
        rs = np.array(runs_by_year[y]) if runs_by_year[y] else np.array([0])
        if len(rs) < 5 or rs.sum() == 0:
            continue
        print(f"  {y:<6}{len(rs):>8}{rs.mean():>8.2f}{np.median(rs):>8.1f}"
              f"{np.percentile(rs, 75):>8.1f}{np.percentile(rs, 90):>8.1f}"
              f"{np.percentile(rs, 95):>8.1f}{rs.max():>8}")

    # Transition probabilities — where does state 3 go?
    print(f"\n  Where does state 3 go NEXT bar? (per year)")
    k_states = int(states[STATE_COL].max()) + 1
    print(f"  {'year':<6}" + "".join(f"{'→s'+str(s):>9}" for s in range(k_states)))
    for y in (2020, 2021, 2022, 2023, 2024, 2025, 2026):
        sub = states[states["year"] == y].sort_index()
        arr = sub[STATE_COL].to_numpy()
        if len(arr) < 100:
            continue
        # Find indices where state == 3 AND next index exists
        idx3 = np.where(arr[:-1] == TARGET_STATE)[0]
        if len(idx3) == 0:
            continue
        nexts = arr[idx3 + 1]
        counts = np.zeros(k_states, dtype=np.int64)
        for s in range(k_states):
            counts[s] = (nexts == s).sum()
        total = counts.sum()
        row = f"  {y:<6}"
        for s in range(k_states):
            row += f"{counts[s]/total*100:>8.1f}%"
        print(row)

    # Feature distribution comparison (mean and median by year)
    print(f"\n  State-3 feature MEANS by year  (top features by |2024−2025 z-score delta|)")
    s3_with_yr = s3.copy()
    rows = []
    for c in FEATURE_COLS:
        if c not in s3_with_yr.columns:
            continue
        try:
            y24 = s3_with_yr.loc[s3_with_yr["year"] == 2024, c].dropna()
            y25 = s3_with_yr.loc[s3_with_yr["year"] == 2025, c].dropna()
            if len(y24) < 100 or len(y25) < 100:
                continue
            std_pool = y24.std()
            delta_z = (y25.mean() - y24.mean()) / std_pool if std_pool > 0 else np.nan
            rows.append((c, y24.mean(), y25.mean(),
                          y25.mean() - y24.mean(), delta_z))
        except Exception:
            pass
    rows.sort(key=lambda r: -abs(r[4]) if not np.isnan(r[4]) else 0)
    print(f"  {'feature':<26}{'2024 mean':>12}{'2025 mean':>12}{'delta':>10}"
          f"{'delta z':>10}")
    for c, m24, m25, d, dz in rows[:14]:
        print(f"  {c:<26}{m24:>+12.3f}{m25:>+12.3f}{d:>+10.3f}{dz:>+10.3f}")

    # Per-year quick reference for top differentiating feature
    if rows:
        top_feat = rows[0][0]
        print(f"\n  Top differentiator: '{top_feat}' — by year (median in state 3):")
        for y in (2020, 2021, 2022, 2023, 2024, 2025, 2026):
            sub = s3.loc[s3["year"] == y, top_feat].dropna()
            if len(sub) >= 30:
                tag = "IS" if y in IS_YEARS else ""
                print(f"    {y}: median={sub.median():+.3f}  mean={sub.mean():+.3f}  "
                      f"n={len(sub):,}  {tag}")


# ───────────────────────────── MAIN ────────────────────────────────

def load_p4_trades():
    parts = []
    for y in range(2020, 2027):
        p = Path(NT_TRADES.format(y))
        if not p.exists():
            continue
        d = pd.read_parquet(p)
        d["year"] = y
        d["entry_ts"] = d["entry_ts"].astype(np.int64)
        d["exit_ts"]  = d["exit_ts"].astype(np.int64)
        d["signal_direction"] = d["signal_direction"].astype(np.int64)
        parts.append(d)
    return pd.concat(parts, ignore_index=True)


def main():
    t0 = time.time()
    trades = load_p4_trades()
    print(f"Loaded {len(trades):,} P4 NT trades across 7 years")

    losers = report_part_a(trades)
    losers.to_parquet(OUT / "p4_losers.parquet", index=False)

    report_part_b()

    print(f"\n[done] {(time.time()-t0)/60:.1f} min")


if __name__ == "__main__":
    main()
