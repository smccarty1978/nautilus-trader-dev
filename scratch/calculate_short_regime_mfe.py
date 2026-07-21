"""Calculate MFE distribution for regimes lasting less than 15 minutes."""
import os, sys, time
import numpy as np
import pandas as pd
from numba import njit
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

PROJECT_ROOT = Path("c:/Users/Scott McCarty/Projects/Nautilus Trader")
os.chdir(PROJECT_ROOT)

ONE_S = {y: f"data/raw/NQ_v0_1s_{y}.parquet" for y in range(2020, 2027)}
ONE_S[2026] = "data/raw/NQ_v0_1s_2026_ytd.parquet"

@njit
def scan_episode_mfe(starts, ends, directions, entry_pxs, ts_1s, high_1s, low_1s):
    n = len(starts)
    mfe_pts = np.zeros(n)
    for i in range(n):
        s = starts[i]
        e = ends[i]
        d = directions[i]
        px = entry_pxs[i]
        
        idx_start = np.searchsorted(ts_1s, s, side='left')
        idx_end = np.searchsorted(ts_1s, e, side='right')
        
        if idx_start >= len(ts_1s):
            continue
            
        j = idx_start
        max_high = px
        min_low = px
        while j < idx_end and j < len(ts_1s):
            h, l = high_1s[j], low_1s[j]
            if h > max_high:
                max_high = h
            if l < min_low:
                min_low = l
            j += 1
            
        if d == 1:
            mfe_pts[i] = max_high - px
        else:
            mfe_pts[i] = px - min_low
            
    return mfe_pts

def run_analysis():
    t0 = time.time()
    
    # Load flips
    df_flips = pd.read_parquet("studies/regime_classification/results/flips_excursion_paths.parquet")
    
    # Filter for regimes lasting < 15 minutes
    df_short = df_flips[df_flips["hold_min_flip"] < 15.0].copy()
    print(f"Total short regimes (< 15 min): {len(df_short):,} (out of {len(df_flips):,} total flips)")
    
    years = sorted(df_short["year"].unique())
    
    all_flips_mfes = []
    conf_flips_mfes = [] # confirmed cohort, measured from flip px
    conf_bar1_mfes = []  # confirmed cohort, measured from bar1 close px
    
    for y in years:
        df_y = df_short[df_short["year"] == y].copy().reset_index(drop=True)
        if len(df_y) == 0:
            continue
            
        print(f"Processing year {y} ({len(df_y)} short episodes)...")
        
        # Load 1s price bars
        p_1s = ONE_S.get(y)
        if not p_1s or not Path(p_1s).exists():
            print(f"Warning: 1s NQ file not found for year {y}")
            continue
            
        bars = pd.read_parquet(p_1s, columns=["high", "low"])
        ts_1s = bars.index.values.astype("int64")
        h_1s = bars["high"].to_numpy(np.float64)
        l_1s = bars["low"].to_numpy(np.float64)
        
        # 1. All Flips
        starts = df_y["entry_ts"].to_numpy(np.int64)
        ends = df_y["exit_ts"].to_numpy(np.int64)
        dirs = df_y["signal_direction"].to_numpy(np.int64)
        px_flips = df_y["entry_px_flip"].to_numpy(np.float64)
        atrs = df_y["entry_atr"].to_numpy(np.float64)
        
        mfe_pts_all = scan_episode_mfe(starts, ends, dirs, px_flips, ts_1s, h_1s, l_1s)
        mfe_atr_all = mfe_pts_all / atrs
        all_flips_mfes.extend(mfe_atr_all)
        
        # 2. Confirmed Cohort
        is_conf = (df_y["bar1_confirm"] == 1).to_numpy()
        if is_conf.sum() > 0:
            # Measured from flip price
            mfe_atr_conf_flip = mfe_atr_all[is_conf]
            conf_flips_mfes.extend(mfe_atr_conf_flip)
            
            # Measured from Bar-1 close price
            # Note: Bar-1 close entry occurs at s + 60s
            starts_bar1 = starts[is_conf] + 60_000_000_000
            ends_bar1 = ends[is_conf]
            dirs_bar1 = dirs[is_conf]
            px_bar1 = df_y["entry_px_bar1"].to_numpy(np.float64)[is_conf]
            atrs_bar1 = atrs[is_conf]
            
            # Ensure bar1 entry time does not exceed exit time
            valid_bar1 = starts_bar1 < ends_bar1
            if valid_bar1.sum() > 0:
                mfe_pts_conf_bar1 = scan_episode_mfe(
                    starts_bar1[valid_bar1], ends_bar1[valid_bar1], dirs_bar1[valid_bar1], 
                    px_bar1[valid_bar1], ts_1s, h_1s, l_1s
                )
                mfe_atr_conf_bar1 = mfe_pts_conf_bar1 / atrs_bar1[valid_bar1]
                conf_bar1_mfes.extend(mfe_atr_conf_bar1)
                
    all_flips_mfes = np.array(all_flips_mfes)
    conf_flips_mfes = np.array(conf_flips_mfes)
    conf_bar1_mfes = np.array(conf_bar1_mfes)
    
    print("\n" + "="*60)
    print("  MFE DISTRIBUTION FOR SHORT REGIMES (< 15 MIN)")
    print("="*60)
    
    # Calculate quantiles
    q_vals = [0.1, 0.2, 0.25, 0.3, 0.4, 0.5, 0.6, 0.7, 0.75, 0.8, 0.9]
    
    def print_distribution(arr, label):
        print(f"\n--- {label} (N={len(arr):,}) ---")
        print(f"  Mean MFE: {np.mean(arr):.4f} ATR")
        print(f"  Min MFE:  {np.min(arr):.4f} ATR")
        print(f"  Max MFE:  {np.max(arr):.4f} ATR")
        print("\n  Quantiles:")
        for q in q_vals:
            val = np.percentile(arr, q * 100)
            print(f"    {q*100:>4.1f}%: {val:.4f} ATR")
            
    print_distribution(all_flips_mfes, "All Flips (Regime < 15m)")
    print_distribution(conf_flips_mfes, "Bar-1 Confirmed (Measured from Flip close)")
    print_distribution(conf_bar1_mfes, "Bar-1 Confirmed (Measured from Bar-1 close entry)")
    
if __name__ == "__main__":
    run_analysis()
