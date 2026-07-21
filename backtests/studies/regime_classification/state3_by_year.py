"""State 3 by year characterization study.

For every year compute on the hmm_4 state-3 cohort:
  Population-level (1m bars labeled state 3):
    - frequency: % of 1m bars in state 3
    - mean realized vol (rv_30s, rv_300s)
    - mean atr_1m
    - state-3 run-length distribution

  Trade-level (NT P4 baseline trades, which require state==3 at flip-bar):
    - mean entry_atr
    - mean MFE (atr-normalized)
    - mean MAE (atr-normalized)
    - mean hold time (min)
    - mean trade PnL (atr-normalized and $) — all trades + regime-flip-only

Hypothesis being tested: 2025 State 3 is structurally different from 2024 State 3,
even though the HMM assigned the same label. If true, a slow HMM (15m/60m features)
might catch the "regime context" the fast HMM is blind to.
"""
from __future__ import annotations
import os, sys, time
from pathlib import Path

import numpy as np
import pandas as pd
from numba import njit

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))
os.chdir(project_root)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

NQ_MULT = 20.0
COMM = 5.0
YEARS = (2020, 2021, 2022, 2023, 2024, 2025, 2026)
IS_YEARS = (2020, 2021, 2022)
OOS_YEARS = (2023, 2024, 2025, 2026)

STATES = Path("studies/regime_classification/results/states_nq_1m.parquet")
FEATS  = Path("studies/regime_classification/results/features_nq_1m.parquet")
TRADES_DIR = Path("backtests/hmm_state_filtered/results")
ONE_S = {y: f"data/raw/NQ_v0_1s_{y}.parquet" for y in range(2019, 2026)}
ONE_S[2026] = "data/raw/NQ_v0_1s_2026_ytd.parquet"


@njit
def walk_mfe_mae(entry_ts, exit_ts, entry_px, dir_arr, atr_arr,
                  ts_1s, h_1s, l_1s):
    n = len(entry_ts)
    mfe = np.full(n, np.nan)
    mae = np.full(n, np.nan)
    for k in range(n):
        T0 = entry_ts[k]; Tx = exit_ts[k]
        ep = entry_px[k]; d = dir_arr[k]; atr = atr_arr[k]
        if T0 < 0 or Tx <= T0 or atr <= 0:
            continue
        i_lo = np.searchsorted(ts_1s, T0, side="left")
        i_hi = np.searchsorted(ts_1s, Tx, side="left")
        if i_hi <= i_lo:
            continue
        best_mfe = 0.0
        best_mae = 0.0
        for j in range(i_lo, i_hi):
            h = h_1s[j]; l = l_1s[j]
            if d == 1:
                pos = h - ep
                neg = ep - l
            else:
                pos = ep - l
                neg = h - ep
            if pos > best_mfe:
                best_mfe = pos
            if neg > best_mae:
                best_mae = neg
        mfe[k] = best_mfe / atr
        mae[k] = best_mae / atr
    return mfe, mae


def load_state_population():
    print("Loading state + feature population...")
    s = pd.read_parquet(STATES, columns=["hmm_4"])
    f = pd.read_parquet(FEATS, columns=["rv_30s", "rv_300s", "atr_1m",
                                          "range_atr_60s", "range_atr_300s",
                                          "year"])
    df = s.join(f, how="inner")
    print(f"  {len(df):,} 1m bars total, years {sorted(df['year'].dropna().unique().astype(int))}")
    return df


def population_stats(pop: pd.DataFrame):
    print(f"\n{'='*92}\n  POPULATION (1m bars labeled state 3): per-year stats\n{'='*92}")
    print(f"  {'year':<6}{'bars':>10}{'state3%':>10}{'rv_30s':>12}{'rv_300s':>12}"
          f"{'atr_1m':>10}{'rng60s':>10}{'rng300s':>10}")
    for y in YEARS:
        yr = pop[pop["year"] == y]
        if len(yr) == 0:
            continue
        s3 = yr[yr["hmm_4"] == 3]
        pct = len(s3) / len(yr)
        marker = "IS " if y in IS_YEARS else "   "
        print(f"  {y:<6}{len(yr):>10,}{pct:>9.2%}"
              f"{s3['rv_30s'].mean():>+12.5f}{s3['rv_300s'].mean():>+12.5f}"
              f"{s3['atr_1m'].mean():>10.3f}"
              f"{s3['range_atr_60s'].mean():>+10.3f}"
              f"{s3['range_atr_300s'].mean():>+10.3f}  {marker}")


def state3_run_lengths(pop: pd.DataFrame):
    """Identify consecutive state-3 runs per year and report length distribution."""
    print(f"\n{'='*92}\n  STATE-3 RUN LENGTHS  (consecutive 1m bars in state 3)\n{'='*92}")
    print(f"  {'year':<6}{'n_runs':>8}{'mean':>8}{'med':>6}{'p75':>6}{'p90':>6}{'p95':>6}{'p99':>7}{'max':>7}")
    pop = pop.sort_index()
    pop["is_s3"] = (pop["hmm_4"] == 3).astype(int)
    pop["run_id"] = (pop["is_s3"].diff().abs().fillna(1).cumsum())
    for y in YEARS:
        yr = pop[pop["year"] == y]
        if len(yr) == 0:
            continue
        s3_yr = yr[yr["is_s3"] == 1]
        # Each run gets its length from the group
        run_lengths = s3_yr.groupby("run_id").size().values
        if len(run_lengths) == 0:
            continue
        marker = "IS " if y in IS_YEARS else "   "
        print(f"  {y:<6}{len(run_lengths):>8,}"
              f"{run_lengths.mean():>8.2f}{int(np.median(run_lengths)):>6}"
              f"{int(np.percentile(run_lengths, 75)):>6}"
              f"{int(np.percentile(run_lengths, 90)):>6}"
              f"{int(np.percentile(run_lengths, 95)):>6}"
              f"{int(np.percentile(run_lengths, 99)):>7}"
              f"{int(run_lengths.max()):>7}  {marker}")


def trade_level_stats():
    print(f"\n  Computing MFE/MAE per trade via 1s walk (per year)...")
    all_rows = []
    for y in YEARS:
        p = TRADES_DIR / f"nq_hmm_4_s3_pt2p0_{y}/trades.parquet"
        if not p.exists():
            continue
        tr = pd.read_parquet(p)
        if len(tr) == 0:
            continue
        # Load 1s data for the year
        one_s_p = ONE_S.get(y)
        if not (one_s_p and Path(one_s_p).exists()):
            print(f"  {y}: 1s file missing; skip MFE/MAE walk")
            continue
        t0 = time.time()
        bars = pd.read_parquet(one_s_p, columns=["high", "low", "close"])
        if bars.index.tz is None:
            bars.index = bars.index.tz_localize("UTC")
        ts_1s = bars.index.values.astype(np.int64)
        h_1s = bars["high"].to_numpy(np.float64)
        l_1s = bars["low"].to_numpy(np.float64)
        e_ts = tr["entry_ts"].astype(np.int64).to_numpy()
        x_ts = tr["exit_ts"].astype(np.int64).to_numpy()
        e_px = tr["entry_px"].astype(np.float64).to_numpy()
        d    = tr["signal_direction"].astype(np.int64).to_numpy()
        atr  = tr["entry_atr"].astype(np.float64).to_numpy()
        mfe, mae = walk_mfe_mae(e_ts, x_ts, e_px, d, atr, ts_1s, h_1s, l_1s)
        tr["year"] = y
        tr["mfe_atr"] = mfe
        tr["mae_atr"] = mae
        tr["hold_min"] = (tr["exit_ts"] - tr["entry_ts"]) / 60e9
        tr["pnl_atr"] = (tr["exit_px"] - tr["entry_px"]) * tr["signal_direction"] / tr["entry_atr"]
        tr["pnl_$"] = (tr["exit_px"] - tr["entry_px"]) * tr["signal_direction"] * NQ_MULT - COMM
        all_rows.append(tr)
        print(f"  {y}: {len(tr)} trades; walk {time.time()-t0:.1f}s")
    return pd.concat(all_rows, ignore_index=True) if all_rows else pd.DataFrame()


def report_trade_stats(tr: pd.DataFrame, only_regime=False):
    label = "regime-exit ONLY" if only_regime else "ALL trades"
    print(f"\n{'='*92}\n  TRADE-LEVEL stats per year — {label}\n{'='*92}")
    print(f"  {'year':<6}{'n':>6}{'win%':>8}{'pnl_$':>10}{'pnl_atr':>10}"
          f"{'MFE':>8}{'MAE':>8}{'hold_m':>8}{'entry_atr':>11}")
    sub = tr.copy()
    if only_regime:
        sub = sub[sub["exit_reason"] == "regime_flip"]
    for y in YEARS:
        yr = sub[sub["year"] == y]
        if len(yr) == 0:
            continue
        marker = "IS " if y in IS_YEARS else "   "
        print(f"  {y:<6}{len(yr):>6}{(yr['pnl_$']>0).mean():>7.1%}"
              f"{yr['pnl_$'].mean():>+10.2f}{yr['pnl_atr'].mean():>+10.3f}"
              f"{yr['mfe_atr'].mean():>+8.3f}{yr['mae_atr'].mean():>+8.3f}"
              f"{yr['hold_min'].mean():>+8.2f}{yr['entry_atr'].mean():>+11.3f}  {marker}")


def comparison_2024_vs_2025(pop: pd.DataFrame, tr: pd.DataFrame):
    """Side-by-side 2024 vs 2025 to test 'same animal' hypothesis."""
    print(f"\n{'='*92}\n  2024 vs 2025  SAME-ANIMAL TEST\n{'='*92}")
    pop24 = pop[(pop["year"] == 2024) & (pop["hmm_4"] == 3)]
    pop25 = pop[(pop["year"] == 2025) & (pop["hmm_4"] == 3)]
    tr24 = tr[tr["year"] == 2024]
    tr25 = tr[tr["year"] == 2025]
    rows = [
        ("State-3 share of year",
            f"{len(pop24)/len(pop[pop.year==2024]):.2%}",
            f"{len(pop25)/len(pop[pop.year==2025]):.2%}"),
        ("State-3 bar count",       f"{len(pop24):,}",          f"{len(pop25):,}"),
        ("Mean rv_30s",             f"{pop24['rv_30s'].mean():+.5f}",   f"{pop25['rv_30s'].mean():+.5f}"),
        ("Mean rv_300s",            f"{pop24['rv_300s'].mean():+.5f}",  f"{pop25['rv_300s'].mean():+.5f}"),
        ("Mean atr_1m",             f"{pop24['atr_1m'].mean():.3f}",    f"{pop25['atr_1m'].mean():.3f}"),
        ("Mean range_atr_60s",      f"{pop24['range_atr_60s'].mean():+.3f}", f"{pop25['range_atr_60s'].mean():+.3f}"),
        ("Mean range_atr_300s",     f"{pop24['range_atr_300s'].mean():+.3f}", f"{pop25['range_atr_300s'].mean():+.3f}"),
        ("Trade count",             f"{len(tr24)}",                     f"{len(tr25)}"),
        ("Trade WR (PT exits + regime wins)",
            f"{(tr24['pnl_$']>0).mean():.1%}",
            f"{(tr25['pnl_$']>0).mean():.1%}"),
        ("Trade MFE (mean ATR)",    f"{tr24['mfe_atr'].mean():+.3f}",   f"{tr25['mfe_atr'].mean():+.3f}"),
        ("Trade MAE (mean ATR)",    f"{tr24['mae_atr'].mean():+.3f}",   f"{tr25['mae_atr'].mean():+.3f}"),
        ("Trade hold (mean min)",   f"{tr24['hold_min'].mean():.2f}",   f"{tr25['hold_min'].mean():.2f}"),
        ("Mean pnl_$",              f"{tr24['pnl_$'].mean():+.2f}",     f"{tr25['pnl_$'].mean():+.2f}"),
        ("Mean entry ATR",          f"{tr24['entry_atr'].mean():.3f}",  f"{tr25['entry_atr'].mean():.3f}"),
    ]
    print(f"  {'metric':<40}{'2024':>15}{'2025':>15}  ratio")
    for name, v24, v25 in rows:
        try:
            f24, f25 = float(v24.replace("%", "").replace(",", "").replace("+", ""))/100.0 \
                        if "%" in v24 else float(v24.replace(",", "").replace("+", "")), \
                       float(v25.replace("%", "").replace(",", "").replace("+", ""))/100.0 \
                        if "%" in v25 else float(v25.replace(",", "").replace("+", ""))
            ratio = f"{f25/f24:.2f}x" if f24 != 0 else "n/a"
        except (ValueError, ZeroDivisionError):
            ratio = ""
        print(f"  {name:<40}{v24:>15}{v25:>15}  {ratio}")


def main():
    pop = load_state_population()
    population_stats(pop)
    state3_run_lengths(pop)
    tr = trade_level_stats()
    if len(tr):
        report_trade_stats(tr, only_regime=False)
        report_trade_stats(tr, only_regime=True)
        comparison_2024_vs_2025(pop, tr)
        out = Path("studies/regime_classification/results/state3_by_year_trades.parquet")
        tr.to_parquet(out, index=False)
        print(f"\n  saved per-trade enriched table → {out}")


if __name__ == "__main__":
    main()
