"""Rolling Retraining & State Drift Study (KMeans)

Tests:
1. 24-month rolling lookback lookups for Quarterly and Monthly cadences.
2. Centroid Euclidean distance alignment to enforce State 0 consistency.
3. Metric summaries comparing Static vs. Quarterly vs. Monthly cadences OOS (2023-2026).
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
def scan_exact_excursions(entry_ts_arr, entry_px_arr, entry_atr_arr, dir_arr,
                          ts_1s, high_1s, low_1s, close_1s):
    N = len(entry_ts_arr)
    mfe_1m = np.full(N, np.nan)
    mae_1m = np.full(N, np.nan)
    term_1m = np.full(N, np.nan)
    
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
                
            running_mfe = max(running_mfe, mfe_t)
            running_mae = max(running_mae, mae_t)
            
            if dt >= 60 * 1_000_000_000 and not recorded_1m:
                mfe_1m[i] = running_mfe / atr
                mae_1m[i] = running_mae / atr
                term_1m[i] = ((c - px_entry) * d) / atr
                recorded_1m = True
                
            j += 1
            
        if j > i_entry:
            last_idx = min(j - 1, len(ts_1s) - 1)
            c = close_1s[last_idx]
            if not recorded_1m:
                mfe_1m[i] = running_mfe / atr
                mae_1m[i] = running_mae / atr
                term_1m[i] = ((c - px_entry) * d) / atr
                
    return mfe_1m, mae_1m, term_1m


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
    t_start = time.time()
    
    # 1. Load flip triggers and excursions
    df_ex = pd.read_parquet("studies/regime_classification/results/flips_excursion_paths.parquet")
    print(f"Loaded {len(df_ex):,} flips.")
    
    # Re-scan for exact terminal outcomes
    all_years_df = []
    for y in sorted(df_ex["year"].unique()):
        year_cohort = df_ex[df_ex["year"] == y].copy()
        if len(year_cohort) == 0:
            continue
        print(f"Scanning 1m excursions for year {y}...")
        try:
            bars = load_1s(y)
        except FileNotFoundError:
            print(f"  Skip year {y}: 1s raw parquets not found.")
            continue
            
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
    print(f"Loaded {len(df_feat):,} 1m feature rows.")
    
    # Drop rows with NaN features
    mask_feat = df_feat[FEATURE_COLS].notna().all(axis=1)
    df_feat_clean = df_feat[mask_feat].copy()
    if df_feat_clean.index.tz is None:
        df_feat_clean.index = df_feat_clean.index.tz_localize("UTC")
    print(f"Cleaned feature rows: {len(df_feat_clean):,}")
    
    # 3. Reference Static Centroid extraction (In-Sample 2020-2022)
    is_mask = df_feat_clean["year"].isin((2020, 2021, 2022))
    df_is = df_feat_clean[is_mask]
    
    scaler_static = StandardScaler()
    X_is_scaled = scaler_static.fit_transform(df_is[FEATURE_COLS].values)
    
    static_km = MiniBatchKMeans(n_clusters=4, random_state=42, n_init=10, batch_size=4096)
    static_km.fit(X_is_scaled)
    
    # Target centroid is the one with the maximum mean range_atr_300s (high-vol expansion)
    range_idx = FEATURE_COLS.index("range_atr_300s")
    target_cluster_idx = np.argmax(static_km.cluster_centers_[:, range_idx])
    target_centroid = static_km.cluster_centers_[target_cluster_idx]
    print(f"Static Target Cluster Index: {target_cluster_idx}")
    print(f"  Target Centroid range_atr_300s z-score: {target_centroid[range_idx]:.3f}")
    
    # Standard scale all features statically for comparison
    X_all_static = scaler_static.transform(df_feat_clean[FEATURE_COLS].values)
    static_labels = static_km.predict(X_all_static)
    df_feat_clean["kmeans_static"] = np.where(static_labels == target_cluster_idx, 0, -1)
    
    # 4. Quarterly Rolling retraining
    print("\nExecuting Quarterly Rolling Retraining...")
    df_feat_clean["kmeans_rolling_q"] = -1
    
    # Get all OOS quarters
    oos_mask = df_feat_clean["year"].isin(OOS_YEARS)
    df_oos = df_feat_clean[oos_mask].copy()
    df_oos["quarter_period"] = df_oos.index.to_period("Q")
    unique_quarters = sorted(df_oos["quarter_period"].unique())
    
    for q in unique_quarters:
        q_start = q.start_time.tz_localize("UTC")
        q_end = q.end_time.tz_localize("UTC")
        
        # Lookback is 24 months preceding q_start
        lookback_start = q_start - pd.DateOffset(months=24)
        lookback_end = q_start - pd.Timedelta(seconds=1)
        
        df_train = df_feat_clean[(df_feat_clean.index >= lookback_start) & (df_feat_clean.index <= lookback_end)]
        df_test = df_oos[df_oos["quarter_period"] == q]
        
        if len(df_train) < 1000 or len(df_test) == 0:
            continue
            
        # Fit scaler and rolling KMeans on lookback window
        scaler = StandardScaler()
        X_train = scaler.fit_transform(df_train[FEATURE_COLS].values)
        
        km = MiniBatchKMeans(n_clusters=4, random_state=42, n_init=10, batch_size=4096)
        km.fit(X_train)
        
        # Centroid alignment via Euclidean distance
        dists = [np.linalg.norm(c - target_centroid) for c in km.cluster_centers_]
        aligned_idx = np.argmin(dists)
        
        # Scale and predict on OOS quarter
        X_test = scaler.transform(df_test[FEATURE_COLS].values)
        test_labels = km.predict(X_test)
        
        df_feat_clean.loc[df_test.index, "kmeans_rolling_q"] = np.where(test_labels == aligned_idx, 0, -1)
        
        # Track average range_atr_300s of aligned State 0 to verify profile stability
        aligned_centroid = km.cluster_centers_[aligned_idx]
        print(f"  Quarter {q}: Aligned cluster={aligned_idx}, dist={dists[aligned_idx]:.3f}, range_atr_300s={aligned_centroid[range_idx]:.3f}")

    # 5. Monthly Rolling retraining
    print("\nExecuting Monthly Rolling Retraining...")
    df_feat_clean["kmeans_rolling_m"] = -1
    df_oos["month_period"] = df_oos.index.to_period("M")
    unique_months = sorted(df_oos["month_period"].unique())
    
    for m in unique_months:
        m_start = m.start_time.tz_localize("UTC")
        m_end = m.end_time.tz_localize("UTC")
        
        # Lookback is 24 months preceding m_start
        lookback_start = m_start - pd.DateOffset(months=24)
        lookback_end = m_start - pd.Timedelta(seconds=1)
        
        df_train = df_feat_clean[(df_feat_clean.index >= lookback_start) & (df_feat_clean.index <= lookback_end)]
        df_test = df_oos[df_oos["month_period"] == m]
        
        if len(df_train) < 1000 or len(df_test) == 0:
            continue
            
        scaler = StandardScaler()
        X_train = scaler.fit_transform(df_train[FEATURE_COLS].values)
        
        km = MiniBatchKMeans(n_clusters=4, random_state=42, n_init=10, batch_size=4096)
        km.fit(X_train)
        
        # Alignment
        dists = [np.linalg.norm(c - target_centroid) for c in km.cluster_centers_]
        aligned_idx = np.argmin(dists)
        
        # Scale and predict on OOS month
        X_test = scaler.transform(df_test[FEATURE_COLS].values)
        test_labels = km.predict(X_test)
        
        df_feat_clean.loc[df_test.index, "kmeans_rolling_m"] = np.where(test_labels == aligned_idx, 0, -1)

    # 6. Match predicted states back to triggers and run simulations
    print("\nMatching predicted states to flip triggers and running simulations...")
    df_flips["kmeans_static"] = lookup_state_causal(
        df_flips["entry_ts"].to_numpy(np.int64),
        df_feat_clean.index.values.astype(np.int64),
        df_feat_clean["kmeans_static"].to_numpy(np.int64),
        60 * 1_000_000_000
    )
    df_flips["kmeans_rolling_q"] = lookup_state_causal(
        df_flips["entry_ts"].to_numpy(np.int64),
        df_feat_clean.index.values.astype(np.int64),
        df_feat_clean["kmeans_rolling_q"].to_numpy(np.int64),
        60 * 1_000_000_000
    )
    df_flips["kmeans_rolling_m"] = lookup_state_causal(
        df_flips["entry_ts"].to_numpy(np.int64),
        df_feat_clean.index.values.astype(np.int64),
        df_feat_clean["kmeans_rolling_m"].to_numpy(np.int64),
        60 * 1_000_000_000
    )
    
    df_flips_oos = df_flips[df_flips["year"].isin(OOS_YEARS)].copy().sort_values("entry_ts")
    
    cadences = [
        ("Static Cadence (Baseline)", "kmeans_static"),
        ("Quarterly Retraining", "kmeans_rolling_q"),
        ("Monthly Retraining", "kmeans_rolling_m")
    ]
    
    print("\n" + "="*80)
    print("  REPORT 1: RETRAINING CADENCE COMPARISON (OOS 2023-2026)")
    print("="*80)
    print(f"  {'Cadence':<30} {'Trades':>8} {'Win%':>8} {'Loss%':>8} {'Flat%':>8} {'Net PnL ($)':>13} {'Max DD ($)':>12} {'PF':>6}")
    print("  " + "-"*95)
    
    rolling_results = {}
    for name, col in cadences:
        sub = df_flips_oos[(df_flips_oos[col] == 0) & (df_flips_oos["entry_atr"] > 15.0)].copy()
        
        if len(sub) == 0:
            print(f"  {name:<30} {0:>8}    -")
            continue
            
        mfe = sub["mfe_1m"].to_numpy()
        mae = sub["mae_1m"].to_numpy()
        term = sub["term_1m"].to_numpy()
        atrs = sub["entry_atr"].to_numpy()
        
        wins = (mfe >= 0.5) & (mae < 1.5)
        losses = (mae >= 1.5) | ((mfe >= 0.5) & (mae >= 1.5))
        flats = ~(wins | losses)
        
        pnl_atr = np.zeros(len(sub))
        pnl_atr[wins] = 0.5
        pnl_atr[losses] = -1.5
        pnl_atr[flats] = term[flats]
        
        pnl_usd = pnl_atr * atrs * 20.0 - 10.0
        pnl_usd = pnl_usd[~np.isnan(pnl_usd)]
        
        cum_pnl = np.cumsum(pnl_usd)
        running_max = np.maximum.accumulate(cum_pnl)
        running_max = np.maximum(running_max, 0.0)
        drawdown = running_max - cum_pnl
        max_dd = np.max(drawdown) if len(drawdown) > 0 else 0.0
        final_pnl = cum_pnl[-1] if len(cum_pnl) > 0 else 0.0
        
        wins_mean = wins.mean()
        losses_mean = losses.mean()
        flats_mean = flats.mean()
        
        pos_pnl = np.sum(pnl_usd[pnl_usd > 0])
        neg_pnl = -np.sum(pnl_usd[pnl_usd < 0])
        pf = pos_pnl / neg_pnl if neg_pnl > 0 else np.nan
        
        print(f"  {name:<30} {len(sub):>8,} {wins_mean:>7.1%} {losses_mean:>7.1%} {flats_mean:>7.1%} {final_pnl:>+12.2f}$ {max_dd:>11.2f}$ {pf:>5.2f}")
        
        # Save year-by-year PnL for Report 2
        y_pnls = {}
        for y in OOS_YEARS:
            y_sub = sub[sub["year"] == y]
            if len(y_sub) == 0:
                y_pnls[y] = 0.0
                continue
            mfe_y = y_sub["mfe_1m"].to_numpy()
            mae_y = y_sub["mae_1m"].to_numpy()
            term_y = y_sub["term_1m"].to_numpy()
            atrs_y = y_sub["entry_atr"].to_numpy()
            
            wins_y = (mfe_y >= 0.5) & (mae_y < 1.5)
            losses_y = (mae_y >= 1.5) | ((mfe_y >= 0.5) & (mae_y >= 1.5))
            flats_y = ~(wins_y | losses_y)
            
            pnl_atr_y = np.zeros(len(y_sub))
            pnl_atr_y[wins_y] = 0.5
            pnl_atr_y[losses_y] = -1.5
            pnl_atr_y[flats_y] = term_y[flats_y]
            
            pnl_usd_y = pnl_atr_y * atrs_y * 20.0 - 10.0
            pnl_usd_y = pnl_usd_y[~np.isnan(pnl_usd_y)]
            y_pnls[y] = pnl_usd_y.sum()
            
        rolling_results[name] = y_pnls
        
    print("\n" + "="*80)
    print("  REPORT 2: YEAR-BY-YEAR DOLLAR PNL EVOLUTION (Static vs. Quarterly)")
    print("="*80)
    print(f"  {'Year':<10} {'Static Net PnL':>18} {'Quarterly Net PnL':>22}")
    print("  " + "-"*55)
    for y in OOS_YEARS:
        static_p = rolling_results["Static Cadence (Baseline)"][y]
        quarterly_p = rolling_results["Quarterly Retraining"][y]
        print(f"  {y:<10} {static_p:>+17.2f}$ {quarterly_p:>+21.2f}$")
    print("  " + "-"*55)
    static_tot = sum(rolling_results["Static Cadence (Baseline)"].values())
    quarterly_tot = sum(rolling_results["Quarterly Retraining"].values())
    print(f"  {'Total':<10} {static_tot:>+17.2f}$ {quarterly_tot:>+21.2f}$")
    
    print(f"\n[done] {(time.time()-t_start)/60:.2f} min")


if __name__ == "__main__":
    main()
