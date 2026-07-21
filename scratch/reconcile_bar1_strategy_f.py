import pandas as pd
import numpy as np
import os
from sklearn.preprocessing import StandardScaler
from sklearn.cluster import MiniBatchKMeans

def main():
    # 1. Load NT trades for Bar1 strategy
    dfs_nt = []
    BASE = "backtests/hmm_state_filtered/results/nq_kmeans_4_s0_sl1p5_minatr15p0_vwapF_qty2_ptr2p0"
    for y in [2023, 2024, 2025, 2026]:
        p = f"{BASE}_{y}/trades.parquet"
        if os.path.exists(p):
            df = pd.read_parquet(p)
            df["year"] = y
            dfs_nt.append(df)
            
    if len(dfs_nt) == 0:
        print("No NT trades found.")
        return
        
    df_nt = pd.concat(dfs_nt, ignore_index=True)
    df_nt["trade_id"] = df_nt.index // 2
    
    # 2. Run simulation on 1s bars
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
    
    # Filter for the active Bar1 cohort: State 0, ATR > 15, bar1_confirm == True, OOS years (2023-2026)
    pop = df_ex[(df_ex["year"].isin((2023, 2024, 2025, 2026))) & 
                (df_ex["kmeans_static_aligned"] == 0) & 
                (df_ex["entry_atr"] > 15.0) & 
                (df_ex["bar1_confirm"] == True)].copy()
                
    print(f"Total triggers in Bar1 OOS population (offline): {len(pop)}")
    print(f"Total trades executed in Nautilus Trader backtest: {len(df_nt) // 2}")
    
    # Load 1s bars for 2023-2026
    bars_cache = {}
    for y in [2023, 2024, 2025, 2026]:
        p = f"data/raw/NQ_v0_1s_{y}.parquet" if y != 2026 else "data/raw/NQ_v0_1s_2026_ytd.parquet"
        if os.path.exists(p):
            df_bars = pd.read_parquet(p, columns=["high", "low", "close"])
            if df_bars.index.tz is None:
                df_bars.index = df_bars.index.tz_localize("UTC")
            bars_cache[y] = df_bars
            
    vwap_z_dict = dict(zip(df_feat_clean.index.values.astype(np.int64), df_feat_clean["vwap_z_abs"].values))
    
    sim_results = []
    for idx, row in pop.iterrows():
        y = int(row["year"])
        bars = bars_cache[y]
        ts_1s = bars.index.astype("int64").to_numpy()
        h_1s = bars["high"].to_numpy()
        l_1s = bars["low"].to_numpy()
        c_1s = bars["close"].to_numpy()
        
        # entry under bar1 confirmation occurs at entry_ts + 60s
        entry_ts = int(row["entry_ts"]) + 60 * 1_000_000_000
        entry_px = float(row["entry_px_bar1"])
        atr = float(row["entry_atr"])
        d = int(row["signal_direction"])
        exit_ts_regime = int(row["exit_ts"])
        exit_px_regime = float(row["exit_px"])
        
        idx_start = np.searchsorted(ts_1s, entry_ts, side="left")
        idx_end = np.searchsorted(ts_1s, exit_ts_regime, side="right") - 1
        idx_end = max(idx_start, min(idx_end, len(ts_1s) - 1))
        
        sl_px = entry_px - d * 1.50 * atr
        pt_0p5 = entry_px + d * 0.50 * atr
        pt_2atr = entry_px + d * 2.00 * atr
        
        # Round target/stops to nearest tick
        sl_px_rounded = round(sl_px * 4) / 4
        pt_0p5_rounded = round(pt_0p5 * 4) / 4
        pt_2atr_rounded = round(pt_2atr * 4) / 4
        
        # 1. Original Idealized Study (with look-ahead bug)
        touch_idx_ideal = -1
        for j in range(idx_start, idx_end + 1):
            h, l = h_1s[j], l_1s[j]
            if (d == 1 and h >= pt_0p5_rounded) or (d == -1 and l <= pt_0p5_rounded):
                touch_idx_ideal = j
                break
                
        if touch_idx_ideal == -1:
            exit_px_c1 = exit_px_c2 = sl_px_rounded
            for j in range(idx_start, idx_end + 1):
                h, l = h_1s[j], l_1s[j]
                if (d == 1 and l <= sl_px_rounded) or (d == -1 and h >= sl_px_rounded):
                    break
            else:
                exit_px_c1 = exit_px_c2 = exit_px_regime
        else:
            touch_ts = ts_1s[touch_idx_ideal]
            t_closed_open = (touch_ts // 60_000_000_000) * 60_000_000_000 - 60_000_000_000
            vwap_z = vwap_z_dict.get(t_closed_open, 1.0)
            
            exit_px_c1 = pt_0p5_rounded
            if vwap_z <= 1.0:
                exit_px_c2 = exit_px_regime
                for j in range(touch_idx_ideal, idx_end + 1):
                    h, l = h_1s[j], l_1s[j]
                    if (d == 1 and l <= sl_px_rounded) or (d == -1 and h >= sl_px_rounded):
                        exit_px_c2 = sl_px_rounded
                        break
                    if (d == 1 and h >= pt_2atr_rounded) or (d == -1 and l <= pt_2atr_rounded):
                        exit_px_c2 = pt_2atr_rounded
                        break
            else:
                exit_px_c2 = pt_0p5_rounded
                
        pnl_ideal_pts = (exit_px_c1 - entry_px) * d + (exit_px_c2 - entry_px) * d
        
        # 2. Corrected Chronological Simulation
        touch_idx_corr = -1
        exit_px_c1_corr = None
        exit_px_c2_corr = None
        
        for j in range(idx_start, idx_end + 1):
            h, l = h_1s[j], l_1s[j]
            if (d == 1 and l <= sl_px_rounded) or (d == -1 and h >= sl_px_rounded):
                exit_px_c1_corr = exit_px_c2_corr = sl_px_rounded
                break
            if (d == 1 and h >= pt_0p5_rounded) or (d == -1 and l <= pt_0p5_rounded):
                touch_idx_corr = j
                break
                
        if touch_idx_corr == -1 and exit_px_c1_corr is None:
            exit_px_c1_corr = exit_px_c2_corr = exit_px_regime
        elif touch_idx_corr != -1:
            touch_ts = ts_1s[touch_idx_corr]
            t_closed_open = (touch_ts // 60_000_000_000) * 60_000_000_000 - 60_000_000_000
            vwap_z = vwap_z_dict.get(t_closed_open, 1.0)
            
            exit_px_c1_corr = pt_0p5_rounded
            if vwap_z <= 1.0:
                exit_px_c2_corr = exit_px_regime
                for j in range(touch_idx_corr, idx_end + 1):
                    h, l = h_1s[j], l_1s[j]
                    if (d == 1 and l <= sl_px_rounded) or (d == -1 and h >= sl_px_rounded):
                        exit_px_c2_corr = sl_px_rounded
                        break
                    if (d == 1 and h >= pt_2atr_rounded) or (d == -1 and l <= pt_2atr_rounded):
                        exit_px_c2_corr = pt_2atr_rounded
                        break
            else:
                exit_px_c2_corr = pt_0p5_rounded
                
        pnl_corr_pts = (exit_px_c1_corr - entry_px) * d + (exit_px_c2_corr - entry_px) * d
        
        sim_results.append({
            "entry_ts": int(row["entry_ts"]), # Save raw-flip entry ts for matching
            "year": y,
            "signal_direction": d,
            "entry_px": entry_px,
            "pnl_ideal_pts": pnl_ideal_pts,
            "pnl_corr_pts": pnl_corr_pts
        })
        
    df_sim = pd.DataFrame(sim_results)
    
    # 3. Perform Reconciled Audit against NT backtest
    matched_rows = []
    for i in range(len(df_nt) // 2):
        c1_nt = df_nt.iloc[2*i]
        c2_nt = df_nt.iloc[2*i+1]
        
        # Match by raw flip timestamp (NT trade has entry_ts = expected_bar1_close = raw_flip_ts + 60s)
        raw_flip_ts = c1_nt["entry_ts"] - 60 * 1_000_000_000
        match = df_sim[np.abs(df_sim["entry_ts"] - raw_flip_ts) < 5_000_000_000]
        
        if len(match) > 0:
            m = match.iloc[0]
            pnl_nt_pts = (c1_nt["exit_px"] - c1_nt["entry_px"]) * c1_nt["signal_direction"] + (c2_nt["exit_px"] - c2_nt["entry_px"]) * c2_nt["signal_direction"]
            
            matched_rows.append({
                "entry_ts": c1_nt["entry_ts"],
                "year": c1_nt["year"],
                "direction": c1_nt["signal_direction"],
                "nt_r1": c1_nt["exit_reason"],
                "nt_r2": c2_nt["exit_reason"],
                "pnl_nt_pts": pnl_nt_pts,
                "pnl_corr_pts": m["pnl_corr_pts"],
                "pnl_ideal_pts": m["pnl_ideal_pts"],
                "diff_corr_pts": pnl_nt_pts - m["pnl_corr_pts"],
                "diff_ideal_pts": pnl_nt_pts - m["pnl_ideal_pts"]
            })
            
    df_match = pd.DataFrame(matched_rows)
    print(f"\nSuccessfully matched {len(df_match)} out of {len(df_nt)//2} event-driven trades.")
    
    # Print year-by-year summary
    print("\nYearly PnL Points Comparison (Matched Trades only):")
    print(f"  {'Year':<4} | {'NT (Event-Driven)':^18} | {'Corrected Causal':^18} | {'Idealized (Look-Ahead)':^22}")
    print("  " + "-" * 70)
    for y in [2023, 2024, 2025, 2026]:
        y_df = df_match[df_match["year"] == y]
        nt_pts = y_df["pnl_nt_pts"].sum()
        corr_pts = y_df["pnl_corr_pts"].sum()
        ideal_pts = y_df["pnl_ideal_pts"].sum()
        print(f"  {y:<4} | {nt_pts:>+14.2f} pts | {corr_pts:>+14.2f} pts | {ideal_pts:>+18.2f} pts")
        
    print("\nTotal OOS Comparison (Matched Trades only):")
    print(f"  Nautilus Trader: {df_match['pnl_nt_pts'].sum():+.2f} pts (${df_match['pnl_nt_pts'].sum()*20.0:,.2f})")
    print(f"  Corrected Study: {df_match['pnl_corr_pts'].sum():+.2f} pts (${df_match['pnl_corr_pts'].sum()*20.0:,.2f})")
    print(f"  Idealized Study: {df_match['pnl_ideal_pts'].sum():+.2f} pts (${df_match['pnl_ideal_pts'].sum()*20.0:,.2f})")
    
    print("\nDiscrepancy Breakdown (Idealized Study lookahead false profits vs. Corrected Study stopped-out trades):")
    # Let's count how many trades were stopped out in the corrected study but hit PT in the idealized study
    discrepant = df_match[df_match["pnl_ideal_pts"] - df_match["pnl_corr_pts"] > 10.0]
    print(f"  Number of look-ahead discrepant trades: {len(discrepant)}")
    print(discrepant[["entry_ts", "year", "direction", "nt_r1", "nt_r2", "pnl_nt_pts", "pnl_corr_pts", "pnl_ideal_pts"]].head(10).to_string())

if __name__ == "__main__":
    main()
