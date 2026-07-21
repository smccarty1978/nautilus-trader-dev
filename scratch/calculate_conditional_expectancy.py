"""Calculate Conditional Expectancy and Giveback Dynamics

Specifically tracks:
- For each MFE threshold reached (+0.25, +0.50, +0.75, +1.00 ATR):
  - Count of trades that reached the threshold.
  - Eventual terminal PnL expectancy (ATR) from entry.
  - Conditional expectancy (ATR) from the threshold point onward to terminal close (the giveback).
  - Distribution of eventual terminal outcomes (Win, Loss, Flat).
Compares Good Years (2024/2025) vs. Bad Years (2023/2026).
"""
from __future__ import annotations
import os, sys, time
from pathlib import Path
import numpy as np
import pandas as pd
from numba import njit
from sklearn.preprocessing import StandardScaler
from sklearn.cluster import MiniBatchKMeans

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))
os.chdir(project_root)

ONE_S = {y: f"data/raw/NQ_v0_1s_{y}.parquet" for y in range(2019, 2027)}
ONE_S[2026] = "data/raw/NQ_v0_1s_2026_ytd.parquet"

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


def load_1s(year):
    import os
    parts = []
    for y in (year - 1, year, year + 1):
        p = ONE_S.get(y)
        if p and os.path.exists(p):
            parts.append(pd.read_parquet(p, columns=["high", "low", "close"]))
    bars = pd.concat(parts).sort_index()
    bars = bars[~bars.index.duplicated(keep="first")]
    if bars.index.tz is None:
        bars.index = bars.index.tz_localize("UTC")
    return bars


@njit
def scan_robust_excursions(entry_ts_arr, entry_px_arr, entry_atr_arr, dir_arr,
                           ts_1s, high_1s, low_1s, close_1s):
    N = len(entry_ts_arr)
    mfe_atr = np.full(N, np.nan)
    mae_atr = np.full(N, np.nan)
    term_atr = np.full(N, np.nan)
    time_to_mfe = np.full(N, np.nan)
    time_to_mae = np.full(N, np.nan)
    
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
        mfe_time_ns = 0.0
        mae_time_ns = 0.0
        
        j = i_entry
        recorded_1m = False
        
        while j < len(ts_1s):
            dt = ts_1s[j] - ts_start
            if dt > 60 * 1_000_000_000:
                break
                
            h, l, c = high_1s[j], low_1s[j], close_1s[j]
            if d == 1:
                mfe_t = h - px_entry
                mae_t = px_entry - l
            else:
                mfe_t = px_entry - l
                mae_t = h - px_entry
                
            if mfe_t > running_mfe:
                running_mfe = mfe_t
                mfe_time_ns = dt
                
            if mae_t > running_mae:
                running_mae = mae_t
                mae_time_ns = dt
                
            if dt >= 60 * 1_000_000_000 and not recorded_1m:
                mfe_atr[i] = running_mfe / atr
                mae_atr[i] = running_mae / atr
                term_atr[i] = ((c - px_entry) * d) / atr
                time_to_mfe[i] = mfe_time_ns / 1_000_000_000.0
                time_to_mae[i] = mae_time_ns / 1_000_000_000.0
                recorded_1m = True
                
            j += 1
            
        if j > i_entry:
            last_idx = min(j - 1, len(ts_1s) - 1)
            c = close_1s[last_idx]
            if not recorded_1m:
                mfe_atr[i] = running_mfe / atr
                mae_atr[i] = running_mae / atr
                term_atr[i] = ((c - px_entry) * d) / atr
                time_to_mfe[i] = mfe_time_ns / 1_000_000_000.0
                time_to_mae[i] = mae_time_ns / 1_000_000_000.0
                
    return mfe_atr, mae_atr, term_atr, time_to_mfe, time_to_mae


def lookup_state_causal(target_ts_arr, state_ts_arr, state_arr, bar_duration_ns, is_int=False):
    state_arr = np.asarray(state_arr).flatten()
    if is_int:
        state_arr = state_arr.astype(np.int64)
    state_ts_arr = np.asarray(state_ts_arr).flatten().astype(np.int64)
    target_ts_arr = np.asarray(target_ts_arr).flatten().astype(np.int64)
    
    query_ts = target_ts_arr - bar_duration_ns
    idx = np.searchsorted(state_ts_arr, query_ts, side="right") - 1
    
    if is_int:
        out = np.full(len(target_ts_arr), -1, dtype=np.int64)
    else:
        out = np.full(len(target_ts_arr), np.nan, dtype=np.float64)
    valid = (idx >= 0) & (idx < len(state_ts_arr))
    out[valid] = state_arr[idx[valid]]
    return out


def main():
    t0 = time.time()
    
    # 1. Load triggers and excursions
    df_ex = pd.read_parquet("studies/regime_classification/results/flips_excursion_paths.parquet")
    
    # Re-scan for excursions
    all_years_df = []
    for y in sorted(df_ex["year"].unique()):
        year_cohort = df_ex[df_ex["year"] == y].copy()
        if len(year_cohort) == 0:
            continue
        try:
            bars = load_1s(y)
        except FileNotFoundError:
            continue
            
        ts_1s = bars.index.astype("int64").to_numpy()
        h_1s = bars["high"].to_numpy(np.float64)
        l_1s = bars["low"].to_numpy(np.float64)
        c_1s = bars["close"].to_numpy(np.float64)
        
        m_atr, ma_atr, t_atr, t_mfe, t_mae = scan_robust_excursions(
            year_cohort["entry_ts"].to_numpy(np.int64),
            year_cohort["entry_px"].to_numpy(np.float64),
            year_cohort["entry_atr"].to_numpy(np.float64),
            year_cohort["signal_direction"].to_numpy(np.int64),
            ts_1s, h_1s, l_1s, c_1s
        )
        
        year_cohort["mfe_1m_atr"] = m_atr
        year_cohort["mae_1m_atr"] = ma_atr
        year_cohort["term_1m_atr"] = t_atr
        year_cohort["time_to_mfe_s"] = t_mfe
        year_cohort["time_to_mae_s"] = t_mae
        
        all_years_df.append(year_cohort)
        
    df_flips = pd.concat(all_years_df, ignore_index=True)
    
    # 2. Load static states
    df_feat = pd.read_parquet("studies/regime_classification/results/features_nq_1m.parquet")
    states_1m = pd.read_parquet("studies/regime_classification/results/states_nq_1m.parquet")
    df_feat["kmeans_static"] = states_1m["kmeans_4"]
    
    mask_feat = df_feat[FEATURE_COLS].notna().all(axis=1)
    df_feat_clean = df_feat[mask_feat].copy()
    if df_feat_clean.index.tz is None:
        df_feat_clean.index = df_feat_clean.index.tz_localize("UTC")
        
    # Re-align Static Target State 0
    df_is = df_feat_clean[df_feat_clean["year"].isin((2020, 2021, 2022))]
    scaler_static = StandardScaler()
    X_is_scaled = scaler_static.fit_transform(df_is[FEATURE_COLS].values)
    static_km = MiniBatchKMeans(n_clusters=4, random_state=42, n_init=10, batch_size=4096)
    static_km.fit(X_is_scaled)
    range_idx = FEATURE_COLS.index("range_atr_300s")
    target_cluster_idx = np.argmax(static_km.cluster_centers_[:, range_idx])
    
    X_all_static = scaler_static.transform(df_feat_clean[FEATURE_COLS].values)
    static_labels = static_km.predict(X_all_static)
    df_feat_clean["kmeans_static_aligned"] = np.where(static_labels == target_cluster_idx, 0, -1)
    
    df_flips["kmeans_static_aligned"] = lookup_state_causal(
        df_flips["entry_ts"].to_numpy(np.int64),
        df_feat_clean.index.values.astype(np.int64),
        df_feat_clean["kmeans_static_aligned"].to_numpy(np.int64),
        60 * 1_000_000_000,
        is_int=True
    )
    
    # Filter to State 0 + ATR > 15 population in OOS (2023-2026)
    pop = df_flips[(df_flips["year"].isin((2023, 2024, 2025, 2026))) & 
                   (df_flips["kmeans_static_aligned"] == 0) & 
                   (df_flips["entry_atr"] > 15.0)].copy()
    
    # Split populations
    win_pop = pop[pop["year"].isin((2024, 2025))].copy()
    bad_pop = pop[pop["year"].isin((2023, 2026))].copy()
    
    def analyze_conditional(df, label):
        print(f"\n" + "="*80)
        print(f"  CONDITIONAL EXPECTANCY STUDY: {label}")
        print("="*80)
        print(f"  {'Threshold T':<12} {'Count':>6} {'% of Total':>10} | {'Term PnL (ATR)':>15} {'Giveback (ATR)':>15} | {'Term Win%':>10} {'Term Loss%':>10}")
        print("  " + "-"*82)
        
        n_total = len(df)
        thresholds = [0.0, 0.25, 0.50, 0.75, 1.00, 1.50]
        
        for t in thresholds:
            if t == 0.0:
                sub = df
            else:
                sub = df[df["mfe_1m_atr"] >= t]
                
            n_sub = len(sub)
            pct_sub = (n_sub / n_total) * 100 if n_total > 0 else 0.0
            
            # Eventual terminal outcome
            mean_term = sub["term_1m_atr"].mean() if n_sub > 0 else 0.0
            giveback = mean_term - t if n_sub > 0 else 0.0
            
            win_rate = (sub["term_1m_atr"] > 0).mean() * 100 if n_sub > 0 else 0.0
            loss_rate = (sub["term_1m_atr"] < 0).mean() * 100 if n_sub > 0 else 0.0
            
            print(f"  {f'>= {t:+.2f} ATR':<12} {n_sub:>6,} {pct_sub:>9.1f}% | {mean_term:>+14.3f}x {giveback:>+14.3f}x | {win_rate:>9.1f}% {loss_rate:>9.1f}%")
            
    analyze_conditional(win_pop, "Good Years (2024/2025)")
    analyze_conditional(bad_pop, "Bad Years (2023/2026)")
    
    print(f"\n[done] {(time.time()-t0)/60:.2f} min")


if __name__ == "__main__":
    main()
