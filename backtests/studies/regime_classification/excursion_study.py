"""Maximum Favorable Excursion (MFE) & Maximum Adverse Excursion (MAE) Study.

For every raw 1m flip entry trigger, tracks the price excursion on 1s bars
forward up to 10 minutes post-entry. Computes the probability of reaching
various MFE thresholds (0.5 to 3.0 ATR) before hitting an MAE stop (0.5 and 1.0 ATR).
Compares the Baseline vs Filtered (kmeans_4 State 0) cohorts.
"""
from __future__ import annotations
import os, sys, time
from pathlib import Path
import numpy as np
import pandas as pd
from numba import njit

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))
os.chdir(project_root)

ONE_S = {y: f"data/raw/NQ_v0_1s_{y}.parquet" for y in range(2019, 2027)}
ONE_S[2026] = "data/raw/NQ_v0_1s_2026_ytd.parquet"
OUT = Path("studies/regime_classification/results")
OOS_YEARS = (2023, 2024, 2025, 2026)


def load_1s(year):
    parts = []
    for y in (year - 1, year, year + 1):
        p = ONE_S.get(y)
        if p and Path(p).exists():
            parts.append(pd.read_parquet(
                p, columns=["high", "low"]))
    bars = pd.concat(parts).sort_index()
    bars = bars[~bars.index.duplicated(keep="first")]
    if bars.index.tz is None:
        bars.index = bars.index.tz_localize("UTC")
    return bars


@njit
def scan_excursions(entry_ts_arr, entry_px_arr, entry_atr_arr, dir_arr,
                    ts_1s, high_1s, low_1s):
    """Scan forward on 1s bars for each trade to calculate excursions.
    
    Returns MFE and MAE arrays at 1m, 5m, 10m in ATR units.
    """
    N = len(entry_ts_arr)
    mfe_1m = np.full(N, np.nan)
    mae_1m = np.full(N, np.nan)
    mfe_5m = np.full(N, np.nan)
    mae_5m = np.full(N, np.nan)
    mfe_10m = np.full(N, np.nan)
    mae_10m = np.full(N, np.nan)
    
    # Pre-calculate searchsorted for speed
    indices = np.searchsorted(ts_1s, entry_ts_arr, side="left")
    
    for i in range(N):
        i_entry = indices[i]
        if i_entry >= len(ts_1s) or entry_atr_arr[i] <= 0:
            continue
            
        px_entry = entry_px_arr[i]
        atr = entry_atr_arr[i]
        d = dir_arr[i]
        ts_start = entry_ts_arr[i]
        
        running_mfe = 0.0
        running_mae = 0.0
        
        # Scan forward up to 600 bars (10 minutes)
        j = i_entry
        while j < len(ts_1s):
            dt = ts_1s[j] - ts_start
            if dt > 600 * 1_000_000_000:
                break
                
            h, l = high_1s[j], low_1s[j]
            if d == 1:
                mfe_t = h - px_entry
                mae_t = px_entry - l
            else:
                mfe_t = px_entry - l
                mae_t = h - px_entry
                
            running_mfe = max(running_mfe, mfe_t)
            running_mae = max(running_mae, mae_t)
            
            # Record at boundaries
            if dt <= 60 * 1_000_000_000:
                mfe_1m[i] = running_mfe / atr
                mae_1m[i] = running_mae / atr
            if dt <= 300 * 1_000_000_000:
                mfe_5m[i] = running_mfe / atr
                mae_5m[i] = running_mae / atr
                
            mfe_10m[i] = running_mfe / atr
            mae_10m[i] = running_mae / atr
            j += 1
            
    return mfe_1m, mae_1m, mfe_5m, mae_5m, mfe_10m, mae_10m


@njit
def race_mfe_vs_mae(mfe_path, mae_path, target_atr, stop_atr):
    """Determine if trade hits target before hitting stop."""
    # Note: since we only have the final recorded MFE/MAE in the window,
    # we simulate the race by checking if the final MFE >= target_atr.
    # To be extremely conservative, if a trade hits the stop_atr in the window,
    # we check if it did so before or after hitting the target. Since we don't
    # have the precise tick-level sequence of MFE/MAE updates in this simple form,
    # we can approximate it: if the final MAE >= stop_atr, we count it as a loss,
    # UNLESS the final MFE was extremely large (i.e. > target_atr).
    # To be strictly conservative and prevent any look-ahead in the race,
    # we will flag a trade as "Won" if:
    # 1. MFE >= target_atr
    # 2. MAE < stop_atr (never hit the stop)
    # This is a strictly conservative lower bound for the win rate.
    return (mfe_path >= target_atr) & (mae_path < stop_atr)


def lookup_state_causal(target_ts_arr, state_ts_arr, state_arr, bar_duration_ns):
    state_arr = np.asarray(state_arr).flatten().astype(np.int64)
    state_ts_arr = np.asarray(state_ts_arr).flatten().astype(np.int64)
    target_ts_arr = np.asarray(target_ts_arr).flatten().astype(np.int64)
    
    query_ts = target_ts_arr - bar_duration_ns
    idx = np.searchsorted(state_ts_arr, query_ts, side="right") - 1
    
    out = np.full(len(target_ts_arr), -1, dtype=np.int64)
    valid = (idx >= 0) & (idx < len(state_ts_arr))
    out[valid] = state_arr[idx[valid]]
    return out


def generate_excursion_table(df, title):
    print(f"\n{'='*78}\n  {title} (n={len(df):,})\n{'='*78}")
    print(f"  {'Timeframe':<10} {'Stop MAE':<10} {'0.5 ATR':>9} {'1.0 ATR':>9} {'1.5 ATR':>9} {'2.0 ATR':>9} {'3.0 ATR':>9}")
    print(f"  {'-'*74}")
    
    for tf_name, mfe_col, mae_col in [("1-minute", "mfe_1m", "mae_1m"),
                                      ("5-minute", "mfe_5m", "mae_5m"),
                                      ("10-minute", "mfe_10m", "mae_10m")]:
        for stop_val in [0.5, 1.0]:
            row_str = f"  {tf_name:<10} {f'{stop_val} ATR':<10}"
            for tgt_val in [0.5, 1.0, 1.5, 2.0, 3.0]:
                mfe_vals = df[mfe_col].to_numpy()
                mae_vals = df[mae_col].to_numpy()
                
                # Causal race: did we reach target_atr before hitting stop_atr?
                # Using the conservative check: MFE >= target AND MAE < stop
                wins = race_mfe_vs_mae(mfe_vals, mae_vals, tgt_val, stop_val)
                wr = wins.mean() * 100
                row_str += f" {wr:>8.1f}%"
            print(row_str)


def main():
    t0 = time.time()
    re_path = "studies/v_a_excursion_regime/results_v0/nt_regime_exit_nq.parquet"
    re = pd.read_parquet(re_path)
    re["entry_ts"] = re["entry_ts"].astype(np.int64)
    re["signal_direction"] = re["signal_direction"].astype(np.int64)
    cohort = re[re["resolved"]].copy()
    print(f"Loaded {len(cohort):,} resolved raw flips from {re_path}")
    
    # Load causal states
    states = pd.read_parquet("studies/regime_classification/results/states_nq_1m.parquet")
    state_ts = states.index.values.astype(np.int64)
    state_arr = states["kmeans_4"].to_numpy(np.int64)
    
    # Look up state causally at entry moment (1m bar duration)
    cohort["kmeans_4_state"] = lookup_state_causal(
        cohort["entry_ts"].to_numpy(np.int64),
        state_ts,
        state_arr,
        60 * 1_000_000_000
    )
    
    # Scan excursions per year and concatenate
    all_years_df = []
    for y in sorted(cohort["year"].unique()):
        year_cohort = cohort[cohort["year"] == y].copy()
        if len(year_cohort) == 0:
            continue
            
        print(f"Scanning excursions for year {y}...")
        try:
            bars = load_1s(y)
        except FileNotFoundError:
            print(f"  Skip year {y}: 1s raw parquets not found.")
            continue
            
        ts_1s = bars.index.astype("int64").to_numpy()
        h_1s = bars["high"].to_numpy(np.float64)
        l_1s = bars["low"].to_numpy(np.float64)
        
        m1, ma1, m5, ma5, m10, ma10 = scan_excursions(
            year_cohort["entry_ts"].to_numpy(np.int64),
            year_cohort["entry_px"].to_numpy(np.float64),
            year_cohort["entry_atr"].to_numpy(np.float64),
            year_cohort["signal_direction"].to_numpy(np.int64),
            ts_1s, h_1s, l_1s
        )
        
        year_cohort["mfe_1m"] = m1
        year_cohort["mae_1m"] = ma1
        year_cohort["mfe_5m"] = m5
        year_cohort["mae_5m"] = ma5
        year_cohort["mfe_10m"] = m10
        year_cohort["mae_10m"] = ma10
        
        all_years_df.append(year_cohort)
        
    df = pd.concat(all_years_df, ignore_index=True)
    
    # Focus on OOS years
    df_oos = df[df["year"].isin(OOS_YEARS)].copy()
    
    # 1. Baseline Cohort (All Raw Flips OOS)
    generate_excursion_table(df_oos, "BASELINE COHORT (All Raw Flips - OOS)")
    
    # 2. Filtered Cohort (kmeans_4 State 0 - OOS)
    df_filtered_oos = df_oos[df_oos["kmeans_4_state"] == 0].copy()
    generate_excursion_table(df_filtered_oos, "FILTERED COHORT (KMeans_4 State 0 - OOS)")
    
    # Save the output excursion dataset
    out_p = OUT / "flips_excursion_paths.parquet"
    df.to_parquet(out_p, index=False)
    print(f"\nSaved excursion dataset to {out_p}")
    print(f"\n[done] {(time.time()-t0)/60:.2f} min")


if __name__ == "__main__":
    main()
