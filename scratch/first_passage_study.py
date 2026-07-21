import pandas as pd
import numpy as np
import os
from sklearn.preprocessing import StandardScaler
from sklearn.cluster import MiniBatchKMeans

def main():
    print("==========================================================================================")
    print("  FIRST-PASSAGE CHRONOLOGICAL ANALYSIS: STATE 0 + ATR > 15 BREAKOUT STRENGTH")
    print("==========================================================================================")
    
    # 1. Load triggers
    df_ex = pd.read_parquet("studies/regime_classification/results/flips_excursion_paths.parquet")
    
    # Align features and kmeans_static
    df_feat = pd.read_parquet("studies/regime_classification/results/features_nq_1m.parquet")
    states_1m = pd.read_parquet("studies/regime_classification/results/states_nq_1m.parquet")
    df_feat["kmeans_static"] = states_1m["kmeans_4"]
    
    mask_feat = df_feat.notna().all(axis=1)
    df_feat_clean = df_feat.copy()
    if df_feat_clean.index.tz is None:
        df_feat_clean.index = df_feat_clean.index.tz_localize("UTC")
        
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
    df_is = df_feat_clean[df_feat_clean["year"].isin((2020, 2021, 2022))].dropna()
    scaler_static = StandardScaler()
    X_is_scaled = scaler_static.fit_transform(df_is[FEATURE_COLS].values)
    static_km = MiniBatchKMeans(n_clusters=4, random_state=42, n_init=10, batch_size=4096)
    static_km.fit(X_is_scaled)
    range_idx = FEATURE_COLS.index("range_atr_300s")
    target_cluster_idx = np.argmax(static_km.cluster_centers_[:, range_idx])
    
    X_all_static = scaler_static.transform(df_feat_clean[FEATURE_COLS].dropna()[FEATURE_COLS].values)
    static_labels = static_km.predict(X_all_static)
    df_feat_clean["kmeans_static_aligned"] = -1
    df_feat_clean.loc[df_feat_clean.dropna().index, "kmeans_static_aligned"] = np.where(static_labels == target_cluster_idx, 0, -1)
    
    def lookup_state_causal(target_ts_arr, state_ts_arr, state_arr, bar_duration_ns):
        state_arr = np.asarray(state_arr).flatten()
        state_ts_arr = np.asarray(state_ts_arr).flatten().astype(np.int64)
        target_ts_arr = np.asarray(target_ts_arr).flatten().astype(np.int64)
        query_ts = target_ts_arr - bar_duration_ns
        idx = np.searchsorted(state_ts_arr, query_ts, side="right") - 1
        out = np.full(len(target_ts_arr), -1, dtype=np.int64)
        valid = (idx >= 0) & (idx < len(state_ts_arr))
        out[valid] = state_arr[idx[valid]]
        return out
        
    df_ex["kmeans_static_aligned"] = lookup_state_causal(
        df_ex["entry_ts"].to_numpy(np.int64),
        df_feat_clean.index.values.astype(np.int64),
        df_feat_clean["kmeans_static_aligned"].to_numpy(np.int64),
        60 * 1_000_000_000
    )
    
    pop = df_ex[(df_ex["year"].isin((2023, 2024, 2025, 2026))) & 
                (df_ex["kmeans_static_aligned"] == 0) & 
                (df_ex["entry_atr"] > 15.0)].copy()
                
    print(f"OOS population size (State 0, ATR > 15): {len(pop)} triggers.")
    
    # Load 1s data
    bars_cache = {}
    for y in [2023, 2024, 2025, 2026]:
        p = f"data/raw/NQ_v0_1s_{y}.parquet" if y != 2026 else "data/raw/NQ_v0_1s_2026_ytd.parquet"
        if os.path.exists(p):
            df_bars = pd.read_parquet(p, columns=["high", "low", "close"])
            if df_bars.index.tz is None:
                df_bars.index = df_bars.index.tz_localize("UTC")
            bars_cache[y] = df_bars
            
    # Setup targets and stops configurations
    # Format: (pt_atr_mult, sl_atr_mult, label)
    setups = [
        (0.25, 0.25, "+0.25 before -0.25"),
        (0.50, 0.50, "+0.50 before -0.50"),
        (0.75, 0.50, "+0.75 before -0.50"),
        (1.00, 0.50, "+1.00 before -0.50")
    ]
    
    results = {label: [] for _, _, label in setups}
    results_by_year = {label: {y: [] for y in [2023, 2024, 2025, 2026]} for _, _, label in setups}
    
    for idx, row in pop.iterrows():
        y = int(row["year"])
        bars = bars_cache[y]
        ts_1s = bars.index.astype("int64").to_numpy()
        h_1s = bars["high"].to_numpy()
        l_1s = bars["low"].to_numpy()
        
        entry_ts = int(row["entry_ts"])
        entry_px = float(row["entry_px"])
        atr = float(row["entry_atr"])
        d = int(row["signal_direction"])
        exit_ts_regime = int(row["exit_ts"])
        
        idx_start = np.searchsorted(ts_1s, entry_ts, side="left")
        idx_end = np.searchsorted(ts_1s, exit_ts_regime, side="right") - 1
        idx_end = max(idx_start, min(idx_end, len(ts_1s) - 1))
        
        for pt_mult, sl_mult, label in setups:
            pt_px = entry_px + d * pt_mult * atr
            sl_px = entry_px - d * sl_mult * atr
            
            # Rounded to NQ tick
            pt_px_rounded = round(pt_px * 4) / 4
            sl_px_rounded = round(sl_px * 4) / 4
            
            outcome = "flat" # default if neither hit before regime flip
            
            for j in range(idx_start, idx_end + 1):
                h, l = h_1s[j], l_1s[j]
                
                # Check stop
                if (d == 1 and l <= sl_px_rounded) or (d == -1 and h >= sl_px_rounded):
                    outcome = "loss"
                    break
                # Check target
                if (d == 1 and h >= pt_px_rounded) or (d == -1 and l <= pt_px_rounded):
                    outcome = "win"
                    break
                    
            results[label].append(outcome)
            results_by_year[label][y].append(outcome)
            
    # Calculate stats
    for pt_mult, sl_mult, label in setups:
        outcomes = results[label]
        n_total = len(outcomes)
        wins = outcomes.count("win")
        losses = outcomes.count("loss")
        flats = outcomes.count("flat")
        
        win_pct = wins / n_total * 100
        loss_pct = losses / n_total * 100
        flat_pct = flats / n_total * 100
        
        # Win-to-Loss ratio on resolved trades (ignoring flats)
        resolved = wins + losses
        win_ratio = wins / resolved * 100 if resolved > 0 else 0.0
        
        print(f"\nSetup: {label} (PT: {pt_mult:.2f} ATR / SL: {sl_mult:.2f} ATR)")
        print(f"  Overall OOS ($n = {n_total}$):")
        print(f"    Target Hit First  : {wins} ({win_pct:.1f}%)")
        print(f"    Stop Hit First    : {losses} ({loss_pct:.1f}%)")
        print(f"    Regime Exit First : {flats} ({flat_pct:.1f}%)")
        print(f"    Win% of Resolved  : {win_ratio:.1f}%")
        
        print("  Year-by-Year Win% of Resolved (Wins / [Wins + Losses]):")
        for y in [2023, 2024, 2025, 2026]:
            y_outcomes = results_by_year[label][y]
            y_total = len(y_outcomes)
            y_wins = y_outcomes.count("win")
            y_losses = y_outcomes.count("loss")
            y_flats = y_outcomes.count("flat")
            
            y_res = y_wins + y_losses
            y_win_ratio = y_wins / y_res * 100 if y_res > 0 else 0.0
            print(f"    {y}: wins={y_wins}, losses={y_losses}, flats={y_flats} | win_ratio={y_win_ratio:.1f}% (total triggers={y_total})")

if __name__ == "__main__":
    main()
