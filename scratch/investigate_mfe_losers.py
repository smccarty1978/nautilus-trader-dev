"""Investigate MFE Distributions before Loss for Static State 0 + ATR > 15

Specifically tracks:
- What percentage of eventual raw losers (terminal PnL < 0) reached +0.25, +0.50, +0.75, +1.00 ATR MFE.
- Mutually exclusive and cumulative buckets of excursion before failure.
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
    
    # Analysis functions
    def analyze_mfe_dist(df, label):
        n_total = len(df)
        # Eventual raw losers (terminal PnL < 0)
        df_losers = df[df["term_1m_atr"] < 0].copy()
        n_losers = len(df_losers)
        
        # Eventual raw losers or flats (terminal PnL <= 0)
        df_non_winners = df[df["term_1m_atr"] <= 0].copy()
        n_non_winners = len(df_non_winners)
        
        print(f"\n--- {label} (Total: {n_total}, Raw Losers < 0: {n_losers}, Losers/Flats <= 0: {n_non_winners}) ---")
        
        thresholds = [0.25, 0.50, 0.75, 1.00, 1.50]
        
        # 1. Cumulative reached threshold for eventual raw losers (<0)
        print("  Percentage of eventual raw losers (Terminal PnL < 0) that first reached MFE threshold:")
        for t in thresholds:
            reached = (df_losers["mfe_1m_atr"] >= t).sum()
            pct = (reached / n_losers) * 100 if n_losers > 0 else 0.0
            print(f"    Reached >= +{t:.2f} ATR MFE: {reached:>3} / {n_losers:>3} ({pct:>5.1f}%)")
            
        # 2. Cumulative reached threshold for eventual losers/flats (<=0)
        print("\n  Percentage of eventual losers/flats (Terminal PnL <= 0) that first reached MFE threshold:")
        for t in thresholds:
            reached = (df_non_winners["mfe_1m_atr"] >= t).sum()
            pct = (reached / n_non_winners) * 100 if n_non_winners > 0 else 0.0
            print(f"    Reached >= +{t:.2f} ATR MFE: {reached:>3} / {n_non_winners:>3} ({pct:>5.1f}%)")
            
        # 3. All trades MFE cumulative distribution
        print("\n  Percentage of ALL trades that reached MFE threshold:")
        for t in thresholds:
            reached = (df["mfe_1m_atr"] >= t).sum()
            pct = (reached / n_total) * 100 if n_total > 0 else 0.0
            print(f"    Reached >= +{t:.2f} ATR MFE: {reached:>3} / {n_total:>3} ({pct:>5.1f}%)")
            
        # 4. Mutually Exclusive Buckets of non-winners (<= 0)
        print("\n  Mutually Exclusive Buckets for trades ending in Loss/Flat (<= 0):")
        # Never reached +0.25 ATR
        never_25 = (df_non_winners["mfe_1m_atr"] < 0.25).sum()
        pct_never = (never_25 / n_non_winners) * 100 if n_non_winners > 0 else 0.0
        print(f"    Never reached +0.25 ATR:       {never_25:>3} / {n_non_winners:>3} ({pct_never:>5.1f}%)")
        
        # Reached +0.25 ATR but <=0 (0.25 <= MFE < 0.50)
        r25 = ((df_non_winners["mfe_1m_atr"] >= 0.25) & (df_non_winners["mfe_1m_atr"] < 0.50)).sum()
        pct_r25 = (r25 / n_non_winners) * 100 if n_non_winners > 0 else 0.0
        print(f"    Reached 0.25 to 0.50 ATR:      {r25:>3} / {n_non_winners:>3} ({pct_r25:>5.1f}%)")
        
        # Reached +0.50 ATR but <=0 (0.50 <= MFE < 1.00)
        r50 = ((df_non_winners["mfe_1m_atr"] >= 0.50) & (df_non_winners["mfe_1m_atr"] < 1.00)).sum()
        pct_r50 = (r50 / n_non_winners) * 100 if n_non_winners > 0 else 0.0
        print(f"    Reached 0.50 to 1.00 ATR:      {r50:>3} / {n_non_winners:>3} ({pct_r50:>5.1f}%)")
        
        # Reached +1.00 ATR but <=0 (1.00 <= MFE < 1.50)
        r100 = ((df_non_winners["mfe_1m_atr"] >= 1.00) & (df_non_winners["mfe_1m_atr"] < 1.50)).sum()
        pct_r100 = (r100 / n_non_winners) * 100 if n_non_winners > 0 else 0.0
        print(f"    Reached 1.00 to 1.50 ATR:      {r100:>3} / {n_non_winners:>3} ({pct_r100:>5.1f}%)")
        
        # Reached +1.50 ATR but <=0 (MFE >= 1.50)
        r150 = (df_non_winners["mfe_1m_atr"] >= 1.50).sum()
        pct_r150 = (r150 / n_non_winners) * 100 if n_non_winners > 0 else 0.0
        print(f"    Reached >= +1.50 ATR:          {r150:>3} / {n_non_winners:>3} ({pct_r150:>5.1f}%)")
        
        return {
            "never_25": pct_never,
            "r25": pct_r25,
            "r50": pct_r50,
            "r100": pct_r100,
            "r150": pct_r150
        }
        
    print("\n" + "="*80)
    print("  MFE ANALYSIS before LOSS: STATIC STATE 0 + ATR > 15")
    print("="*80)
    
    r_win = analyze_mfe_dist(win_pop, "Good Years (2024/2025)")
    r_bad = analyze_mfe_dist(bad_pop, "Bad Years (2023/2026)")
    
    # Print the clean table requested by the user
    print("\n" + "="*80)
    print("  USER REQUESTED MUTUALLY EXCLUSIVE BREAKOUT VS TRADE MGMT TABLE (Non-Winners <= 0)")
    print("="*80)
    print(f"  {'Bucket':<32} {'Good Years':>15} {'Bad Years':>15}")
    print("  " + "-"*64)
    print(f"  {'Never reached +0.25 ATR':<32} {r_win['never_25']:>13.1f}% {r_bad['never_25']:>13.1f}%")
    print(f"  {'Reached +0.25 ATR then lost/flat':<32} {r_win['r25']:>13.1f}% {r_bad['r25']:>13.1f}%")
    print(f"  {'Reached +0.50 ATR then lost/flat':<32} {r_win['r50']:>13.1f}% {r_bad['r50']:>13.1f}%")
    print(f"  {'Reached +1.00 ATR then lost/flat':<32} {r_win['r100']:>13.1f}% {r_bad['r100']:>13.1f}%")
    print(f"  {'Reached +1.50 ATR then lost/flat':<32} {r_win['r150']:>13.1f}% {r_bad['r150']:>13.1f}%")
    
    print(f"\n[done] {(time.time()-t0)/60:.2f} min")


if __name__ == "__main__":
    main()
