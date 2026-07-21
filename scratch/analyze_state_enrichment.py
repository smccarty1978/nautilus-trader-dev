"""Perform Elite/Good/Fakeout State Distribution & Enrichment Study."""
from __future__ import annotations
import os, sys, time
from pathlib import Path
import numpy as np
import pandas as pd
from numba import njit

# Reconfigure stdout for UTF-8
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

PROJECT_ROOT = Path("c:/Users/Scott McCarty/Projects/Nautilus Trader")
os.chdir(PROJECT_ROOT)

# 1s NQ data paths
ONE_S = {y: f"data/raw/NQ_v0_1s_{y}.parquet" for y in range(2020, 2027)}
ONE_S[2026] = "data/raw/NQ_v0_1s_2026_ytd.parquet"

def load_1s(year):
    p = ONE_S.get(year)
    if p and Path(p).exists():
        bars = pd.read_parquet(p, columns=["high", "low", "close"])
        # Ensure UTC timezone
        if bars.index.tz is None:
            bars.index = bars.index.tz_localize("UTC")
        return bars
    else:
        raise FileNotFoundError(f"1s NQ file not found for year {year}")

@njit
def scan_exact_regime_excursions(entry_ts_arr, entry_px_arr, exit_ts_arr, entry_atr_arr, dir_arr,
                                 ts_1s, high_1s, low_1s):
    N = len(entry_ts_arr)
    mfe_regime = np.full(N, np.nan)
    mae_regime = np.full(N, np.nan)
    
    indices = np.searchsorted(ts_1s, entry_ts_arr, side="left")
    
    for i in range(N):
        i_entry = indices[i]
        if i_entry >= len(ts_1s) or entry_atr_arr[i] <= 0:
            continue
            
        px_entry = entry_px_arr[i]
        atr = entry_atr_arr[i]
        d = dir_arr[i]
        ts_start = entry_ts_arr[i]
        ts_end = exit_ts_arr[i]
        
        running_mfe = 0.0
        running_mae = 0.0
        
        j = i_entry
        while j < len(ts_1s):
            t_curr = ts_1s[j]
            if t_curr > ts_end:
                break
                
            h, l = high_1s[j], low_1s[j]
            if d == 1:
                mfe_t = h - px_entry
                mae_t = px_entry - l
            else:
                mfe_t = px_entry - l
                mae_t = h - px_entry
                
            running_mfe = max(running_mfe, mfe_t)
            running_mae = max(running_mae, running_mae) # wait, bug check: running_mae = max(running_mae, mae_t)
            # Let's write this correctly:
            running_mae = max(running_mae, mae_t)
            
            j += 1
            
        mfe_regime[i] = running_mfe / atr
        mae_regime[i] = running_mae / atr
        
    return mfe_regime, mae_regime

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

def compute_metrics_and_states(df, states_1m, states_5m):
    # Tactical state lookup (1m hmm_4)
    df["causal_hmm_1m"] = lookup_state_causal(
        df["entry_ts"].to_numpy(np.int64),
        states_1m.index.values.astype(np.int64),
        states_1m["hmm_4"].to_numpy(np.int64),
        60 * 1_000_000_000
    )
    # Macro state lookup (5m hmm_3)
    df["causal_hmm_5m"] = lookup_state_causal(
        df["entry_ts"].to_numpy(np.int64),
        states_5m.index.values.astype(np.int64),
        states_5m["hmm_3"].to_numpy(np.int64),
        300 * 1_000_000_000
    )
    
    # Calculate exact MFE/MAE up to exit_ts for both Raw Flip and Bar-1 confirmed entry
    years = sorted(df["year"].unique())
    
    mfe_flip_all = np.full(len(df), np.nan)
    mae_flip_all = np.full(len(df), np.nan)
    mfe_bar1_all = np.full(len(df), np.nan)
    mae_bar1_all = np.full(len(df), np.nan)
    
    for y in years:
        mask_y = df["year"] == y
        df_y = df[mask_y]
        if len(df_y) == 0:
            continue
            
        print(f"Scanning exact excursions for year {y}...")
        try:
            bars_1s = load_1s(y)
        except Exception as e:
            print(f"Error loading 1s data for {y}: {e}")
            continue
            
        ts_1s = bars_1s.index.values.astype("int64")
        h_1s = bars_1s["high"].to_numpy(np.float64)
        l_1s = bars_1s["low"].to_numpy(np.float64)
        
        # Raw Flips
        mfe_f, mae_f = scan_exact_regime_excursions(
            df_y["entry_ts"].to_numpy(np.int64),
            df_y["entry_px"].to_numpy(np.float64),
            df_y["exit_ts"].to_numpy(np.int64),
            df_y["entry_atr"].to_numpy(np.float64),
            df_y["signal_direction"].to_numpy(np.int64),
            ts_1s, h_1s, l_1s
        )
        mfe_flip_all[mask_y] = mfe_f
        mae_flip_all[mask_y] = mae_f
        
        # Bar-1 Confirmed Flips
        # entry_ts for bar1 is entry_ts + 60s
        entry_ts_bar1 = df_y["entry_ts"].to_numpy(np.int64) + 60 * 1_000_000_000
        mfe_b, mae_b = scan_exact_regime_excursions(
            entry_ts_bar1,
            df_y["entry_px_bar1"].to_numpy(np.float64),
            df_y["exit_ts"].to_numpy(np.int64),
            df_y["entry_atr"].to_numpy(np.float64),
            df_y["signal_direction"].to_numpy(np.int64),
            ts_1s, h_1s, l_1s
        )
        mfe_bar1_all[mask_y] = mfe_b
        mae_bar1_all[mask_y] = mae_b
        
    df["mfe_flip_exact"] = mfe_flip_all
    df["mae_flip_exact"] = mae_flip_all
    df["mfe_bar1_exact"] = mfe_bar1_all
    df["mae_bar1_exact"] = mae_bar1_all
    
    return df

def run_enrichment_analysis(df_cohort, state_col, state_label, cohort_name):
    # Filter out trades where state or excursions are nan
    df_clean = df_cohort.dropna(subset=[state_col, "mfe_exact", "mae_exact"]).copy()
    df_clean[state_col] = df_clean[state_col].astype(int)
    
    # Filter out state = -1 (invalid lookup)
    df_clean = df_clean[df_clean[state_col] != -1]
    
    total_n = len(df_clean)
    if total_n == 0:
        return
        
    # Buckets definition
    # Elite: MFE >= 2.0 ATR, MAE <= 1.0 ATR
    # Good: MFE >= 1.0 ATR, MAE <= 1.0 ATR
    # Fakeout: MFE < 0.5 ATR
    # Giveback: MFE >= 1.5 ATR but negative terminal PnL
    # Runner: MFE >= 3.0 ATR
    df_clean["is_elite"] = (df_clean["mfe_exact"] >= 2.0) & (df_clean["mae_exact"] <= 1.0)
    df_clean["is_good"] = (df_clean["mfe_exact"] >= 1.0) & (df_clean["mae_exact"] <= 1.0)
    df_clean["is_fakeout"] = df_clean["mfe_exact"] < 0.5
    df_clean["is_giveback"] = (df_clean["mfe_exact"] >= 1.5) & (df_clean["pnl_atr"] < 0.0)
    df_clean["is_runner"] = df_clean["mfe_exact"] >= 3.0
    
    buckets = {
        "Base (All)": df_clean,
        "Elite (MFE>=2, MAE<=1)": df_clean[df_clean["is_elite"]],
        "Good (MFE>=1, MAE<=1)": df_clean[df_clean["is_good"]],
        "Fakeout (MFE<0.5)": df_clean[df_clean["is_fakeout"]],
        "Giveback (MFE>=1.5, PnL<0)": df_clean[df_clean["is_giveback"]],
        "Runner (MFE>=3)": df_clean[df_clean["is_runner"]]
    }
    
    states = sorted(df_clean[state_col].unique())
    
    print(f"\n==============================================================")
    print(f"Cohort: {cohort_name} | State Model: {state_label}")
    print(f"==============================================================")
    
    # Let's print Base Counts
    base_counts = df_clean[state_col].value_counts().sort_index()
    base_shares = base_counts / total_n
    
    print(f"Total deduplicated trades analyzed: {total_n}")
    print(f"Base State Distribution:")
    for s in states:
        count = base_counts.get(s, 0)
        share = base_shares.get(s, 0.0)
        print(f"  State {s}: {count:>5} trades ({share:>6.1%})")
        
    print("\nState Distribution & Enrichment Ratio by Bucket:")
    header = f"{'Bucket':<27} | " + " | ".join(f"St{s} Share (Enrich)" for s in states)
    print(header)
    print("-" * len(header))
    
    for bname, bdf in buckets.items():
        b_n = len(bdf)
        if b_n == 0:
            row_str = f"{bname:<27} | " + " | ".join(f"{'0.0%':>6} (0.00x)" for s in states)
            print(row_str)
            continue
            
        b_counts = bdf[state_col].value_counts().sort_index()
        b_shares = b_counts / b_n
        
        cols = []
        for s in states:
            b_share = b_shares.get(s, 0.0)
            base_share = base_shares.get(s, 0.0)
            enrich = b_share / base_share if base_share > 0 else 0.0
            cols.append(f"{b_share:>6.1%} ({enrich:>5.2f}x)")
            
        print(f"{bname:<27} | " + " | ".join(cols) + f"  (n={b_n})")

    # Let's also run this Year-by-Year for Elite and Fakeout buckets to check Scenario A vs B
    print("\n--- Year-by-Year Enrichment for Elite and Fakeout buckets ---")
    years = sorted(df_clean["year"].unique())
    for s in states:
        print(f"\nState {s} Year-by-Year Profile:")
        print(f"  {'Year':<4} | {'Base N':<6} | {'Base%':<6} | {'Elite N':<7} | {'Elite%':<6} | {'Elite Enrichment':<16} | {'Fake N':<6} | {'Fake%':<5} | {'Fake Enrichment':<15}")
        print(f"  {'-'*98}")
        for y in years:
            df_y = df_clean[df_clean["year"] == y]
            y_base_n = len(df_y)
            if y_base_n == 0:
                continue
            
            y_s_base_n = len(df_y[df_y[state_col] == s])
            y_s_base_pct = y_s_base_n / y_base_n
            
            df_y_elite = df_y[df_y["is_elite"]]
            y_elite_tot = len(df_y_elite)
            y_s_elite_n = len(df_y_elite[df_y_elite[state_col] == s])
            y_s_elite_pct = y_s_elite_n / y_elite_tot if y_elite_tot > 0 else 0.0
            y_s_elite_enrich = y_s_elite_pct / y_s_base_pct if y_s_base_pct > 0 else 0.0
            
            df_y_fake = df_y[df_y["is_fakeout"]]
            y_fake_tot = len(df_y_fake)
            y_s_fake_n = len(df_y_fake[df_y_fake[state_col] == s])
            y_s_fake_pct = y_s_fake_n / y_fake_tot if y_fake_tot > 0 else 0.0
            y_s_fake_enrich = y_s_fake_pct / y_s_base_pct if y_s_base_pct > 0 else 0.0
            
            print(f"  {y:<4} | {y_s_base_n:>6} | {y_s_base_pct:>5.1%} | {y_s_elite_n:>7} | {y_s_elite_pct:>5.1%} | {y_s_elite_enrich:>15.2f}x | {y_s_fake_n:>6} | {y_s_fake_pct:>4.1%} | {y_s_fake_enrich:>14.2f}x")

def main():
    t0 = time.time()
    
    # 1. Load the flips excursion paths dataset
    print("Loading flips excursion paths parquet...")
    df_flips = pd.read_parquet("studies/regime_classification/results/flips_excursion_paths.parquet")
    print(f"Loaded {len(df_flips):,} flips.")
    
    # 2. Load tactical 1m and macro 5m states
    print("Loading causal HMM states...")
    states_1m = pd.read_parquet("studies/regime_classification/results/states_nq_1m.parquet")
    states_5m = pd.read_parquet("studies/regime_classification/results/states_nq_5m.parquet")
    
    # 3. Compute causal lookup and exact MFE/MAE values for each trade
    print("Running exact excursion calculations & state lookup...")
    df_flips = compute_metrics_and_states(df_flips, states_1m, states_5m)
    
    # Now build the Raw Flips cohort
    # We want to deduplicate by entry_ts to collapse c1/c2 dual contracts
    print("\nBuilding Raw Flips Cohort...")
    # Map variables for Raw Flips
    df_raw = df_flips.copy()
    df_raw["mfe_exact"] = df_raw["mfe_flip_exact"]
    df_raw["mae_exact"] = df_raw["mae_flip_exact"]
    df_raw["pnl_atr"] = df_raw["regime_pnl_atr_flip"]
    
    # Deduplicate: Collapse entry_ts to one row per trade-event with pnl summed
    # (Since MFE and MAE are identical for dual contracts, we take first)
    df_raw_dedup = df_raw.groupby("entry_ts").agg({
        "mfe_exact": "first",
        "mae_exact": "first",
        "pnl_atr": "first", # wait, for pnl_atr, it is the per-contract pnl in ATR. Summing it would double it, but the definition of giveback is negative terminal PnL, so sign is what matters. Let's sum or take first (first is fine as it represents 1 contract and sign is identical)
        "year": "first",
        "causal_hmm_1m": "first",
        "causal_hmm_5m": "first",
        "bar1_confirm": "first"
    }).reset_index()
    
    # Filter for RTH to keep it clean (if in_rth or similar exists, wait, do we need it? Let's check.
    # We can check if all trades are in_rth. The flips dataset has trades in RTH mostly. Let's do all).
    
    # Now build Bar-1 Confirmed Cohort
    print("\nBuilding Bar-1 Confirmed Cohort...")
    df_bar1 = df_flips[df_flips["bar1_confirm"] == 1].copy()
    df_bar1["mfe_exact"] = df_bar1["mfe_bar1_exact"]
    df_bar1["mae_exact"] = df_bar1["mae_bar1_exact"]
    df_bar1["pnl_atr"] = df_bar1["regime_pnl_atr_bar1"]
    
    df_bar1_dedup = df_bar1.groupby("entry_ts").agg({
        "mfe_exact": "first",
        "mae_exact": "first",
        "pnl_atr": "first",
        "year": "first",
        "causal_hmm_1m": "first",
        "causal_hmm_5m": "first"
    }).reset_index()
    
    # Run the sweeps!
    # Short Timeframe (1m HMM - hmm_4) on Raw Flips
    run_enrichment_analysis(df_raw_dedup, "causal_hmm_1m", "1m HMM (hmm_4)", "Raw Flips")
    
    # Short Timeframe (1m HMM - hmm_4) on Bar-1 Confirmed Flips
    run_enrichment_analysis(df_bar1_dedup, "causal_hmm_1m", "1m HMM (hmm_4)", "Bar-1 Confirmed")
    
    # Long Timeframe (5m HMM - hmm_3) on Raw Flips
    run_enrichment_analysis(df_raw_dedup, "causal_hmm_5m", "5m HMM (hmm_3)", "Raw Flips")
    
    # Long Timeframe (5m HMM - hmm_3) on Bar-1 Confirmed Flips
    run_enrichment_analysis(df_bar1_dedup, "causal_hmm_5m", "5m HMM (hmm_3)", "Bar-1 Confirmed")
    
    print(f"\nCompleted in {(time.time() - t0)/60:.2f} minutes.")

if __name__ == "__main__":
    main()
