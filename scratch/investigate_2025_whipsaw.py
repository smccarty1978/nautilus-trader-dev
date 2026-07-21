"""Investigate 2025 Whipsaw & Trade Factory Phenomenon

Compares:
1. Realized vol, efficiency, chop, reversals, and session transitions of 2024 vs 2025.
2. Consecutive state duration (run length) of Quarterly Rolling State 0 in 2024 vs 2025.
3. Realized excursion (MFE / MAE) profiles.
"""
from __future__ import annotations
import os, sys, time
from pathlib import Path
import numpy as np
import pandas as pd
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


def main():
    t0 = time.time()
    
    # 1. Load flip triggers and excursions
    df_ex = pd.read_parquet("studies/regime_classification/results/flips_excursion_paths.parquet")
    print(f"Loaded {len(df_ex):,} flips.")
    
    # Re-scan for exact terminal outcomes
    all_years_df = []
    for y in (2024, 2025):
        year_cohort = df_ex[df_ex["year"] == y].copy()
        if len(year_cohort) == 0:
            continue
        print(f"Scanning 1m excursions for year {y}...")
        try:
            bars = load_1s(y)
        except FileNotFoundError:
            print(f"  Skip year {y}: 1s raw parquets not found.")
            continue
            
        from scratch.rolling_regime_study import scan_exact_excursions
        
        ts_1s = bars.index.astype("int64").to_numpy()
        h_1s = bars["high"].to_numpy(np.float64)
        l_1s = bars["low"].to_numpy(np.float64)
        c_1s = bars["close"].to_numpy(np.float64)
        
        m1, ma1, t1 = scan_exact_excursions(
            year_cohort["entry_ts"].to_numpy(np.int64),
            year_cohort["entry_px"].to_numpy(np.float64),
            year_cohort["entry_atr"].to_numpy(np.float64),
            year_cohort["signal_direction"].to_numpy(np.int64),
            ts_1s, h_1s, l_1s, c_1s
        )
        
        year_cohort["mfe_1m"] = m1
        year_cohort["mae_1m"] = ma1
        year_cohort["term_1m"] = t1
        all_years_df.append(year_cohort)
        
    df_flips = pd.concat(all_years_df, ignore_index=True)
    
    # 2. Load 1m raw features
    features_p = Path("studies/regime_classification/results/features_nq_1m.parquet")
    df_feat = pd.read_parquet(features_p)
    
    mask_feat = df_feat[FEATURE_COLS].notna().all(axis=1)
    df_feat_clean = df_feat[mask_feat].copy()
    if df_feat_clean.index.tz is None:
        df_feat_clean.index = df_feat_clean.index.tz_localize("UTC")
        
    # 3. Fit Static KMeans to get target centroid
    is_mask = df_feat_clean["year"].isin((2020, 2021, 2022))
    df_is = df_feat_clean[is_mask]
    scaler_static = StandardScaler()
    X_is_scaled = scaler_static.fit_transform(df_is[FEATURE_COLS].values)
    static_km = MiniBatchKMeans(n_clusters=4, random_state=42, n_init=10, batch_size=4096)
    static_km.fit(X_is_scaled)
    range_idx = FEATURE_COLS.index("range_atr_300s")
    target_cluster_idx = np.argmax(static_km.cluster_centers_[:, range_idx])
    target_centroid = static_km.cluster_centers_[target_cluster_idx]
    
    # 4. Quarterly Rolling retraining
    df_feat_clean["kmeans_rolling_q"] = -1
    df_oos = df_feat_clean[df_feat_clean["year"].isin((2024, 2025))].copy()
    df_oos["quarter_period"] = df_oos.index.to_period("Q")
    unique_quarters = sorted(df_oos["quarter_period"].unique())
    
    for q in unique_quarters:
        q_start = q.start_time.tz_localize("UTC")
        
        lookback_start = q_start - pd.DateOffset(months=24)
        lookback_end = q_start - pd.Timedelta(seconds=1)
        
        df_train = df_feat_clean[(df_feat_clean.index >= lookback_start) & (df_feat_clean.index <= lookback_end)]
        df_test = df_oos[df_oos["quarter_period"] == q]
        
        if len(df_train) < 1000 or len(df_test) == 0:
            continue
            
        scaler = StandardScaler()
        X_train = scaler.fit_transform(df_train[FEATURE_COLS].values)
        km = MiniBatchKMeans(n_clusters=4, random_state=42, n_init=10, batch_size=4096)
        km.fit(X_train)
        
        dists = [np.linalg.norm(c - target_centroid) for c in km.cluster_centers_]
        aligned_idx = np.argmin(dists)
        
        X_test = scaler.transform(df_test[FEATURE_COLS].values)
        test_labels = km.predict(X_test)
        df_feat_clean.loc[df_test.index, "kmeans_rolling_q"] = np.where(test_labels == aligned_idx, 0, -1)

    # Match back to triggers
    df_flips["kmeans_rolling_q"] = lookup_state_causal(
        df_flips["entry_ts"].to_numpy(np.int64),
        df_feat_clean.index.values.astype(np.int64),
        df_feat_clean["kmeans_rolling_q"].to_numpy(np.int64),
        60 * 1_000_000_000
    )
    
    # 5. ANALYSIS COMPARISON
    # Filter to OOS Quarterly Rolling State 0 triggers in 2024 and 2025
    trig_2024 = df_flips[(df_flips["year"] == 2024) & (df_flips["kmeans_rolling_q"] == 0) & (df_flips["entry_atr"] > 15.0)].copy()
    trig_2025 = df_flips[(df_flips["year"] == 2025) & (df_flips["kmeans_rolling_q"] == 0) & (df_flips["entry_atr"] > 15.0)].copy()
    
    print("\n" + "="*80)
    print("  EXCURSION & TRADE PROFILE COMPARISON: 2024 vs 2025")
    print("="*80)
    print(f"  {'Metric':<30} {'2024 State 0':>18} {'2025 State 0':>18}")
    print("  " + "-"*60)
    print(f"  {'Total Trades':<30} {len(trig_2024):>18,} {len(trig_2025):>18,}")
    
    # Excursion metrics
    mfe_24, mae_24 = trig_24_mfe = trig_2024["mfe_1m"].mean(), trig_2024["mae_1m"].mean()
    mfe_25, mae_25 = trig_25_mfe = trig_2025["mfe_1m"].mean(), trig_2025["mae_1m"].mean()
    print(f"  {'Mean MFE (1m)':<30} {mfe_24:>17.3f}x {mfe_25:>17.3f}x")
    print(f"  {'Mean MAE (1m)':<30} {mae_24:>17.3f}x {mae_25:>17.3f}x")
    
    # Optimal win%, loss%, flat%
    wins_24 = ((trig_2024["mfe_1m"] >= 0.5) & (trig_2024["mae_1m"] < 1.5)).mean() * 100
    wins_25 = ((trig_2025["mfe_1m"] >= 0.5) & (trig_2025["mae_1m"] < 1.5)).mean() * 100
    print(f"  {'Win% (0.5/1.5)':<30} {wins_24:>17.1f}% {wins_25:>17.1f}%")
    
    loss_24 = ((trig_2024["mae_1m"] >= 1.5) | ((trig_2024["mfe_1m"] >= 0.5) & (trig_2024["mae_1m"] >= 1.5))).mean() * 100
    loss_25 = ((trig_2025["mae_1m"] >= 1.5) | ((trig_2025["mfe_1m"] >= 0.5) & (trig_2025["mae_1m"] >= 1.5))).mean() * 100
    print(f"  {'Loss% (0.5/1.5)':<30} {loss_24:>17.1f}% {loss_25:>17.1f}%")
    
    # 6. FEATURE COMPARISON OF PREDICTED STATE 0 BARS
    df_feat_24 = df_feat_clean[(df_feat_clean["year"] == 2024) & (df_feat_clean["kmeans_rolling_q"] == 0)]
    df_feat_25 = df_feat_clean[(df_feat_clean["year"] == 2025) & (df_feat_clean["kmeans_rolling_q"] == 0)]
    
    print("\n" + "="*80)
    print("  FEATURE SIGNATURE OF ALIGNED STATE 0 BARS: 2024 vs 2025")
    print("="*80)
    print(f"  {'Feature':<30} {'2024 Mean (Raw)':>18} {'2025 Mean (Raw)':>18}")
    print("  " + "-"*60)
    
    comp_features = [
        "rv_30s", "rv_300s", "efficiency_300s", "chop_ratio_300s",
        "n_dir_changes_60s", "range_atr_300s", "vol_expansion"
    ]
    
    for f in comp_features:
        m_24 = df_feat_24[f].mean()
        m_25 = df_feat_25[f].mean()
        print(f"  {f:<30} {m_24:>18.4f} {m_25:>18.4f}")
        
    # 7. STATE DURATION & TRANSITIONS per Session
    # Calculate state runs
    def calc_run_lengths(state_series):
        runs = []
        current_run = 0
        for val in state_series:
            if val == 0:
                current_run += 1
            else:
                if current_run > 0:
                    runs.append(current_run)
                    current_run = 0
        if current_run > 0:
            runs.append(current_run)
        return np.array(runs)
        
    runs_24 = calc_run_lengths(df_feat_clean[df_feat_clean["year"] == 2024]["kmeans_rolling_q"].values)
    runs_25 = calc_run_lengths(df_feat_clean[df_feat_clean["year"] == 2025]["kmeans_rolling_q"].values)
    
    # Calculate session transitions (how many times model enters/leaves State 0 per day)
    # We can approximate sessions by date
    sessions_24 = df_feat_clean[df_feat_clean["year"] == 2024].groupby(df_feat_clean[df_feat_clean["year"] == 2024].index.date)["kmeans_rolling_q"]
    transitions_24 = [((g.values[:-1] != g.values[1:]) & (g.values[1:] == 0)).sum() for _, g in sessions_24]
    
    sessions_25 = df_feat_clean[df_feat_clean["year"] == 2025].groupby(df_feat_clean[df_feat_clean["year"] == 2025].index.date)["kmeans_rolling_q"]
    transitions_25 = [((g.values[:-1] != g.values[1:]) & (g.values[1:] == 0)).sum() for _, g in sessions_25]
    
    print("\n" + "="*80)
    print("  STATE RUN-LENGTH & SESSION DYNAMICS: 2024 vs 2025")
    print("="*80)
    print(f"  {'Metric':<30} {'2024 State 0':>18} {'2025 State 0':>18}")
    print("  " + "-"*60)
    print(f"  {'Mean State Duration (min)':<30} {runs_24.mean():>18.2f} {runs_25.mean():>18.2f}")
    print(f"  {'Max State Duration (min)':<30} {runs_24.max():>18.2f} {runs_25.max():>18.2f}")
    print(f"  {'State Entries per Session':<30} {np.mean(transitions_24):>18.2f} {np.mean(transitions_25):>18.2f}")
    print(f"  {'Total State Entries (OOS)':<30} {len(runs_24):>18,} {len(runs_25):>18,}")
    
    print(f"\n[done] {(time.time()-t0)/60:.2f} min")


if __name__ == "__main__":
    main()
