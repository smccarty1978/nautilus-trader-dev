"""Analyze Win-Rate Lift monotonicity with volatility (ATR).

Compares Filtered (KMeans_4 State 0) vs Baseline win rates across ATR thresholds
to test if the relative predictive edge is monotonic with volatility.
"""
from __future__ import annotations
import os, sys, time
from pathlib import Path
import numpy as np
import pandas as pd
from numba import njit

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))
os.chdir(project_root)

ONE_S = {y: f"data/raw/NQ_v0_1s_{y}.parquet" for y in range(2019, 2027)}
ONE_S[2026] = "data/raw/NQ_v0_1s_2026_ytd.parquet"
OOS_YEARS = (2023, 2024, 2025, 2026)


def load_1s(year):
    parts = []
    for y in (year - 1, year, year + 1):
        p = ONE_S.get(y)
        if p and Path(p).exists():
            parts.append(pd.read_parquet(
                p, columns=["high", "low", "close"]))
    bars = pd.concat(parts).sort_index()
    bars = bars[~bars.index.duplicated(keep="first")]
    if bars.index.tz is None:
        bars.index = bars.index.tz_localize("UTC")
    return bars


@njit
def scan_exact_excursions(entry_ts_arr, entry_px_arr, entry_atr_arr, dir_arr,
                          ts_1s, high_1s, low_1s, close_1s):
    N = len(entry_ts_arr)
    mfe_1m = np.full(N, np.nan)
    mae_1m = np.full(N, np.nan)
    term_1m = np.full(N, np.nan)
    
    mfe_5m = np.full(N, np.nan)
    mae_5m = np.full(N, np.nan)
    term_5m = np.full(N, np.nan)
    
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
        
        j = i_entry
        recorded_1m = False
        recorded_5m = False
        
        while j < len(ts_1s):
            dt = ts_1s[j] - ts_start
            if dt > 300 * 1_000_000_000:
                break
                
            h, l, c = high_1s[j], low_1s[j], close_1s[j]
            if d == 1:
                mfe_t = h - px_entry
                mae_t = px_entry - l
            else:
                mfe_t = px_entry - l
                mae_t = h - px_entry
                
            running_mfe = max(running_mfe, mfe_t)
            running_mae = max(running_mae, mae_t)
            
            if dt >= 60 * 1_000_000_000 and not recorded_1m:
                mfe_1m[i] = running_mfe / atr
                mae_1m[i] = running_mae / atr
                term_1m[i] = ((c - px_entry) * d) / atr
                recorded_1m = True
                
            if dt >= 300 * 1_000_000_000 and not recorded_5m:
                mfe_5m[i] = running_mfe / atr
                mae_5m[i] = running_mae / atr
                term_5m[i] = ((c - px_entry) * d) / atr
                recorded_5m = True
                
            j += 1
            
        if j > i_entry:
            last_idx = min(j - 1, len(ts_1s) - 1)
            c = close_1s[last_idx]
            if not recorded_1m:
                mfe_1m[i] = running_mfe / atr
                mae_1m[i] = running_mae / atr
                term_1m[i] = ((c - px_entry) * d) / atr
            if not recorded_5m:
                mfe_5m[i] = running_mfe / atr
                mae_5m[i] = running_mae / atr
                term_5m[i] = ((c - px_entry) * d) / atr
                
    return mfe_1m, mae_1m, term_1m, mfe_5m, mae_5m, term_5m


def main():
    t0 = time.time()
    df_ex = pd.read_parquet("studies/regime_classification/results/flips_excursion_paths.parquet")
    print(f"Loaded {len(df_ex):,} flips.")
    
    # Re-scan to extract exact terminal prices
    all_years_df = []
    for y in sorted(df_ex["year"].unique()):
        year_cohort = df_ex[df_ex["year"] == y].copy()
        if len(year_cohort) == 0:
            continue
            
        print(f"Scanning exact terminal prices for year {y}...")
        try:
            bars = load_1s(y)
        except FileNotFoundError:
            print(f"  Skip year {y}: 1s raw parquets not found.")
            continue
            
        ts_1s = bars.index.astype("int64").to_numpy()
        h_1s = bars["high"].to_numpy(np.float64)
        l_1s = bars["low"].to_numpy(np.float64)
        c_1s = bars["close"].to_numpy(np.float64)
        
        m1, ma1, t1, m5, ma5, t5 = scan_exact_excursions(
            year_cohort["entry_ts"].to_numpy(np.int64),
            year_cohort["entry_px"].to_numpy(np.float64),
            year_cohort["entry_atr"].to_numpy(np.float64),
            year_cohort["signal_direction"].to_numpy(np.int64),
            ts_1s, h_1s, l_1s, c_1s
        )
        
        year_cohort["mfe_1m"] = m1
        year_cohort["mae_1m"] = ma1
        year_cohort["term_1m"] = t1
        year_cohort["mfe_5m"] = m5
        year_cohort["mae_5m"] = ma5
        year_cohort["term_5m"] = t5
        
        all_years_df.append(year_cohort)
        
    df = pd.concat(all_years_df, ignore_index=True)
    df_oos = df[df["year"].isin(OOS_YEARS)].copy()
    
    atr_thresholds = [0.0, 8.0, 10.0, 12.0, 15.0, 18.0, 20.0, 25.0, 30.0]
    
    # We will test win-rate lifts for symmetric 1.0 ATR brackets
    print(f"\n==============================================================")
    print(f"  WIN-RATE LIFT SENSITIVITY: 5m Symmetric Bracket (1.0 ATR PT/SL)")
    print(f"==============================================================")
    print(f"  {'ATR Thresh':<12} {'Base Trades':>12} {'Filtered n':>12} {'Base Win%':>10} {'Filt Win%':>10} {'Lift (pp)':>10}")
    print(f"  {'-'*74}")
    
    for thresh in atr_thresholds:
        # Baseline cohort
        sub_base = df_oos[df_oos["entry_atr"] >= thresh]
        # Filtered cohort
        sub_filt = sub_base[sub_base["kmeans_4_state"] == 0]
        
        if len(sub_filt) < 5:
            continue
            
        # Compute wins for baseline
        mfe_b = sub_base["mfe_5m"].to_numpy()
        mae_b = sub_base["mae_5m"].to_numpy()
        wins_b = (mfe_b >= 1.0) & (mae_b < 1.0)
        wr_base = wins_b.mean() * 100
        
        # Compute wins for filtered
        mfe_f = sub_filt["mfe_5m"].to_numpy()
        mae_f = sub_filt["mae_5m"].to_numpy()
        wins_f = (mfe_f >= 1.0) & (mae_f < 1.0)
        wr_filt = wins_f.mean() * 100
        
        lift = wr_filt - wr_base
        thresh_str = "None" if thresh == 0.0 else f"> {thresh}"
        print(f"  {thresh_str:<12} {len(sub_base):>12,} {len(sub_filt):>12,} {wr_base:>9.1%}% {wr_filt:>9.1%}% {lift:>+9.1f}pp")
        
    print(f"\n==============================================================")
    print(f"  WIN-RATE LIFT SENSITIVITY: 1m Asymmetric Bracket (0.50 PT / 1.50 SL)")
    print(f"==============================================================")
    print(f"  {'ATR Thresh':<12} {'Base Trades':>12} {'Filtered n':>12} {'Base Win%':>10} {'Filt Win%':>10} {'Lift (pp)':>10}")
    print(f"  {'-'*74}")
    
    for thresh in atr_thresholds:
        # Baseline cohort
        sub_base = df_oos[df_oos["entry_atr"] >= thresh]
        # Filtered cohort
        sub_filt = sub_base[sub_base["kmeans_4_state"] == 0]
        
        if len(sub_filt) < 5:
            continue
            
        # Compute wins for baseline
        mfe_b = sub_base["mfe_1m"].to_numpy()
        mae_b = sub_base["mae_1m"].to_numpy()
        wins_b = (mfe_b >= 0.5) & (mae_b < 1.5)
        wr_base = wins_b.mean() * 100
        
        # Compute wins for filtered
        mfe_f = sub_filt["mfe_1m"].to_numpy()
        mae_f = sub_filt["mae_1m"].to_numpy()
        wins_f = (mfe_f >= 0.5) & (mae_f < 1.5)
        wr_filt = wins_f.mean() * 100
        
        lift = wr_filt - wr_base
        thresh_str = "None" if thresh == 0.0 else f"> {thresh}"
        print(f"  {thresh_str:<12} {len(sub_base):>12,} {len(sub_filt):>12,} {wr_base:>9.1%}% {wr_filt:>9.1%}% {lift:>+9.1f}pp")
        
    print(f"\n[done] {(time.time()-t0)/60:.2f} min")


if __name__ == "__main__":
    main()
