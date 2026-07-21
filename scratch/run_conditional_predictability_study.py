"""Run conditional path predictability study for flip entries."""
from __future__ import annotations
import os, sys, time
from pathlib import Path
import numpy as np
import pandas as pd
from numba import njit

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

PROJECT_ROOT = Path("c:/Users/Scott McCarty/Projects/Nautilus Trader")
os.chdir(PROJECT_ROOT)

ONE_S = {y: f"data/raw/NQ_v0_1s_{y}.parquet" for y in range(2020, 2027)}
ONE_S[2026] = "data/raw/NQ_v0_1s_2026_ytd.parquet"

B_ITER = 1000  # 1k iterations for fast, robust slope CIs
SEED = 42
NQ_MULT = 20.0
FRICTION_1X = 10.0
FRICTION_2X = 20.0

HORIZONS_MIN = [2, 5, 15, 30]
GATES_MIN = [1, 2, 3, 5, 10]

@njit
def scan_causal_paths_numba(entry_pxs, directions, index_entries, index_Ks, index_KHs, close_1s, high_1s, low_1s):
    n = len(entry_pxs)
    # Features at K (points)
    net_excursions = np.zeros(n)
    mfe_so_fars = np.zeros(n)
    mae_so_fars = np.zeros(n)
    speeds = np.zeros(n)
    
    # Targets (points)
    fwd_returns = np.zeros(n)
    fwd_mfes = np.zeros(n)
    fwd_maes = np.zeros(n)
    
    for i in range(n):
        px_entry = entry_pxs[i]
        d = directions[i]
        idx_entry = index_entries[i]
        idx_K = index_Ks[i]
        idx_KH = index_KHs[i]
        
        # Price at K
        px_K = close_1s[idx_K]
        net_excursions[i] = (px_K - px_entry) * d
        
        # Scan excursions in (idx_entry, idx_K]
        running_mfe_K = 0.0
        running_mae_K = 0.0
        path_len = 0.0
        prev_px = px_entry
        
        for j in range(idx_entry + 1, idx_K + 1):
            h, l = high_1s[j], low_1s[j]
            c = close_1s[j]
            if d == 1:
                mfe_t = h - px_entry
                mae_t = px_entry - l
            else:
                mfe_t = px_entry - l
                mae_t = h - px_entry
            running_mfe_K = max(running_mfe_K, mfe_t)
            running_mae_K = max(running_mae_K, mae_t)
            path_len += abs(c - prev_px)
            prev_px = c
            
        mfe_so_fars[i] = running_mfe_K
        mae_so_fars[i] = running_mae_K
        speeds[i] = ((px_K - px_entry) * d) / (path_len + 1e-8)
        
        # Calculate targets from K to K+H (in range idx_K to idx_KH)
        px_KH = close_1s[idx_KH]
        fwd_returns[i] = (px_KH - px_K) * d
        
        running_mfe_KH = 0.0
        running_mae_KH = 0.0
        for j in range(idx_K + 1, idx_KH + 1):
            h, l = high_1s[j], low_1s[j]
            if d == 1:
                mfe_t = h - px_K
                mae_t = px_K - l
            else:
                mfe_t = px_K - l
                mae_t = h - px_K
            running_mfe_KH = max(running_mfe_KH, mfe_t)
            running_mae_KH = max(running_mae_KH, mae_t)
            
        fwd_mfes[i] = running_mfe_KH
        fwd_maes[i] = running_mae_KH
        
    return net_excursions, mfe_so_fars, mae_so_fars, speeds, fwd_returns, fwd_mfes, fwd_maes

def load_1s(year):
    p = ONE_S.get(year)
    if p and Path(p).exists():
        bars = pd.read_parquet(p, columns=["high", "low", "close", "open"])
        if bars.index.tz is None:
            bars.index = bars.index.tz_localize("UTC")
        return bars
    raise FileNotFoundError(f"1s NQ file not found for year {year}")

def calculate_beta_slope(x, y):
    n = len(x)
    if n < 3:
        return 0.0
    sum_x = x.sum()
    sum_y = y.sum()
    sum_xy = np.dot(x, y)
    sum_xx = np.dot(x, x)
    denom = n * sum_xx - sum_x**2
    if denom == 0:
        return 0.0
    return (n * sum_xy - sum_x * sum_y) / denom

def run_conditional_study():
    t0 = time.time()
    
    # 1. Load Close-Confirmed flips
    df_flips = pd.read_parquet("studies/regime_classification/results/flips_excursion_paths.parquet")
    df_bar1 = df_flips[df_flips["bar1_confirm"] == 1].copy()
    
    df_dedup = df_bar1.groupby("entry_ts").agg({
        "entry_px_bar1": "first",
        "entry_px_flip": "first",
        "exit_ts": "first",
        "exit_px": "first",
        "signal_direction": "first",
        "entry_atr": "first",
        "year": "first"
    }).reset_index()
    
    df_dedup["bar1_close_confirmed"] = ((df_dedup["entry_px_bar1"] - df_dedup["entry_px_flip"]) * df_dedup["signal_direction"] > 0).astype(int)
    df_cohort = df_dedup[df_dedup["bar1_close_confirmed"] == 1].copy().reset_index(drop=True)
    print(f"Loaded {len(df_cohort):,} Close-Confirmed episodes.")
    
    # Load tactical 1m HMM states to lookup ATR at entry t0 (Bar1 close)
    print("Loading 1m states...")
    states_1m = pd.read_parquet("studies/regime_classification/results/states_nq_1m.parquet")
    state_ts_ns = states_1m.index.values.astype(np.int64)
    state_atrs = states_1m["atr_1m"].to_numpy(np.float64)
    
    def lookup_atr(target_ts):
        idx = np.searchsorted(state_ts_ns, target_ts, side="right") - 1
        if 0 <= idx < len(state_ts_ns):
            return state_atrs[idx]
        return 15.0
        
    years = sorted(df_cohort["year"].unique())
    
    # We will accumulate all results into a single large list of dataframes
    all_calculated_rows = []
    
    for y in years:
        df_y = df_cohort[df_cohort["year"] == y].copy().reset_index(drop=True)
        if len(df_y) == 0:
            continue
            
        print(f"\n==================================================")
        print(f"Processing year {y} (Episodes: {len(df_y)})...")
        print(f"==================================================")
        
        try:
            bars = load_1s(y)
        except Exception as e:
            print(f"Error loading 1s data for {y}: {e}")
            continue
            
        ts_1s = bars.index.values.astype("int64")
        o_1s = bars["open"].to_numpy(np.float64)
        h_1s = bars["high"].to_numpy(np.float64)
        l_1s = bars["low"].to_numpy(np.float64)
        c_1s = bars["close"].to_numpy(np.float64)
        
        n_ep = len(df_y)
        treat_px = df_y["entry_px_bar1"].to_numpy(np.float64)
        treat_dir = df_y["signal_direction"].to_numpy(np.int64)
        treat_ts = df_y["entry_ts"].to_numpy(np.int64) + 60_000_000_000  # Bar-1 close time
        
        treat_idx = np.searchsorted(ts_1s, treat_ts, side="left")
        treat_idx = np.clip(treat_idx, 0, len(ts_1s) - 1)
        
        # Look up exact ATR at t0 (Bar1 close) for each treatment
        treat_atrs = np.array([lookup_atr(t) for t in treat_ts])
        
        # We calculate metrics for all K and H combinations
        # We store them in a year-specific dictionary to assemble a dataframe later
        y_data = {
            "entry_ts": treat_ts - 60_000_000_000, # flip time
            "year": df_y["year"].values,
            "signal_direction": treat_dir,
            "entry_atr": treat_atrs,
            "entry_px": treat_px
        }
        
        for K in GATES_MIN:
            t_K = treat_ts + K * 60_000_000_000
            idx_K = np.searchsorted(ts_1s, t_K, side="left")
            idx_K = np.clip(idx_K, 0, len(ts_1s) - 1)
            
            for H in HORIZONS_MIN:
                t_KH = t_K + H * 60_000_000_000
                idx_KH = np.searchsorted(ts_1s, t_KH, side="left")
                idx_KH = np.clip(idx_KH, 0, len(ts_1s) - 1)
                
                print(f"  Calculating (K={K}m, H={H}m)...")
                
                net_ex, mfe_sf, mae_sf, speed, fwd_ret, fwd_mfe, fwd_mae = scan_causal_paths_numba(
                    treat_px, treat_dir, treat_idx, idx_K, idx_KH, c_1s, h_1s, l_1s
                )
                
                # Normalize by ATR
                y_data[f"net_ex_K{K}"] = net_ex / treat_atrs
                y_data[f"mfe_sf_K{K}"] = mfe_sf / treat_atrs
                y_data[f"mae_sf_K{K}"] = mae_sf / treat_atrs
                y_data[f"speed_K{K}"] = speed
                
                y_data[f"fwd_ret_K{K}_H{H}"] = fwd_ret / treat_atrs
                y_data[f"fwd_mfe_K{K}_H{H}"] = fwd_mfe / treat_atrs
                y_data[f"fwd_mae_K{K}_H{H}"] = fwd_mae / treat_atrs
                y_data[f"fwd_ret_pts_K{K}_H{H}"] = fwd_ret # raw points
                
        df_y_calculated = pd.DataFrame(y_data)
        all_calculated_rows.append(df_y_calculated)
        
    # Concatenate all years
    df_all = pd.concat(all_calculated_rows, ignore_index=True)
    os.makedirs("studies/forward_return/results", exist_ok=True)
    df_all.to_parquet("studies/forward_return/results/conditional_study_data.parquet")
    print(f"\nSaved raw study metrics to studies/forward_return/results/conditional_study_data.parquet")
    
    # 2. Run analysis on the compiled master dataframe
    run_analysis_reporting(df_all)
    
    print(f"\n[done] Total runtime: {(time.time() - t0)/60:.2f} min")

def run_analysis_reporting(df):
    print("\n" + "="*60)
    print("  RUNNING CONDITIONAL PATH PREDICTABILITY ANALYSIS")
    print("="*60)
    
    cohorts = {
        "ALL": df,
        "LONG": df[df["signal_direction"] == 1],
        "SHORT": df[df["signal_direction"] == -1]
    }
    
    summary_rows = []
    
    for c_name, df_sub in cohorts.items():
        if len(df_sub) == 0:
            continue
            
        print(f"\n==================================================")
        print(f"Cohort: {c_name} (N = {len(df_sub):,})")
        print(f"==================================================")
        
        # Pre-generate bootstrap day indices for this cohort
        df_sub = df_sub.copy()
        df_sub["date"] = pd.to_datetime(df_sub["entry_ts"], unit="ns").dt.date
        unique_days = sorted(df_sub["date"].unique())
        day_to_indices = {d: np.where(df_sub["date"] == d)[0] for d in unique_days}
        day_list = list(unique_days)
        n_days = len(day_list)
        
        boot_rng = np.random.RandomState(SEED)
        boot_indices = []
        for b in range(B_ITER):
            resample_days = boot_rng.choice(day_list, size=n_days, replace=True)
            boot_indices.append(np.concatenate([day_to_indices[d] for d in resample_days]))
            
        for K in GATES_MIN:
            # Excursion at K
            x = df_sub[f"net_ex_K{K}"].to_numpy()
            
            # Bucketing
            buckets = [
                (" <0 ATR", x < 0),
                ("0-0.25", (x >= 0) & (x < 0.25)),
                ("0.25-0.5", (x >= 0.25) & (x < 0.5)),
                ("0.5-1.0", (x >= 0.5) & (x < 1.0)),
                (" >=1.0", x >= 1.0)
            ]
            
            for H in HORIZONS_MIN:
                y = df_sub[f"fwd_ret_K{K}_H{H}"].to_numpy()
                y_pts = df_sub[f"fwd_ret_pts_K{K}_H{H}"].to_numpy()
                
                # A. Regression and Bootstrap CI
                obs_slope = calculate_beta_slope(x, y)
                
                boot_slopes = np.zeros(B_ITER)
                for b in range(B_ITER):
                    idx = boot_indices[b]
                    boot_slopes[b] = calculate_beta_slope(x[idx], y[idx])
                
                slope_ci_lower = np.percentile(boot_slopes, 2.5)
                slope_ci_upper = np.percentile(boot_slopes, 97.5)
                
                print(f"\nGate K={K}m -> Horizon H={H}m:")
                print(f"  Linear Regression Slope (Forward Return ~ Excursion_K): {obs_slope:+.4f}")
                print(f"  95% Bootstrap CI: [{slope_ci_lower:+.4f}, {slope_ci_upper:+.4f}]")
                
                # B. Bucketed Analysis
                print(f"  {'Bucket (net ex)':<16} | {'N':<6} | {'Mean Ret (ATR)':<14} | {'% Pos':<7} | {'Net 1x USD':<11} | {'Net 2x USD':<11}")
                print(f"  {'-'*16:<16} | {'-'*6:<6} | {'-'*14:<14} | {'-'*7:<7} | {'-'*11:<11} | {'-'*11:<11}")
                
                bucket_results = []
                for b_label, mask in buckets:
                    b_n = mask.sum()
                    if b_n == 0:
                        print(f"  {b_label:<16} | {b_n:<6} | {'N/A':<14} | {'N/A':<7} | {'N/A':<11} | {'N/A':<11}")
                        continue
                        
                    mean_ret = y[mask].mean()
                    pct_pos = (y[mask] > 0).mean() * 100
                    
                    # USD calculation net of friction
                    raw_usd = y_pts[mask] * NQ_MULT
                    net_1x = raw_usd.mean() - FRICTION_1X
                    net_2x = raw_usd.mean() - FRICTION_2X
                    
                    print(f"  {b_label:<16} | {b_n:<6} | {mean_ret:>+14.4f} | {pct_pos:>6.1f}% | ${net_1x:>+9.2f} | ${net_2x:>+9.2f}")
                    
                    bucket_results.append({
                        "bucket": b_label,
                        "n": b_n,
                        "mean_ret_atr": mean_ret,
                        "pct_pos": pct_pos,
                        "net_1x_usd": net_1x,
                        "net_2x_usd": net_2x
                    })
                    
                # Save to list
                summary_rows.append({
                    "cohort": c_name,
                    "K": K,
                    "H": H,
                    "n_total": len(df_sub),
                    "slope": obs_slope,
                    "slope_ci_lower": slope_ci_lower,
                    "slope_ci_upper": slope_ci_upper,
                    "buckets": bucket_results
                })
                
    # Save summary results
    import pickle
    with open("studies/forward_return/results/conditional_study_summary.pkl", "wb") as f:
        pickle.dump(summary_rows, f)
        
if __name__ == "__main__":
    run_conditional_study()
