import pandas as pd
import numpy as np
import os
from sklearn.preprocessing import StandardScaler
from sklearn.cluster import MiniBatchKMeans

def main():
    print("==========================================================================================")
    print("  POST-ENTRY EVOLUTION STUDY: WINNING VS FAILING EXPANSIONS ON 1S PATHS")
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
                
    # Load 1s data
    bars_cache = {}
    for y in [2023, 2024, 2025, 2026]:
        p = f"data/raw/NQ_v0_1s_{y}.parquet" if y != 2026 else "data/raw/NQ_v0_1s_2026_ytd.parquet"
        if os.path.exists(p):
            df_bars = pd.read_parquet(p, columns=["high", "low", "close"])
            if df_bars.index.tz is None:
                df_bars.index = df_bars.index.tz_localize("UTC")
            bars_cache[y] = df_bars
            
    vwap_z_dict = dict(zip(df_feat_clean.index.values.astype(np.int64), df_feat_clean["vwap_z_abs"].values))
    
    active_cohort = []
    
    for idx, row in pop.iterrows():
        y = int(row["year"])
        bars = bars_cache[y]
        ts_1s = bars.index.astype("int64").to_numpy()
        h_1s = bars["high"].to_numpy()
        l_1s = bars["low"].to_numpy()
        c_1s = bars["close"].to_numpy()
        
        entry_ts = int(row["entry_ts"])
        entry_px = float(row["entry_px"])
        atr = float(row["entry_atr"])
        d = int(row["signal_direction"])
        exit_ts_regime = int(row["exit_ts"])
        
        idx_start = np.searchsorted(ts_1s, entry_ts, side="left")
        idx_end = np.searchsorted(ts_1s, exit_ts_regime, side="right") - 1
        idx_end = max(idx_start, min(idx_end, len(ts_1s) - 1))
        
        pt_0p5 = entry_px + d * 0.50 * atr
        pt_2p0 = entry_px + d * 2.00 * atr
        sl_px = entry_px - d * 1.50 * atr
        
        pt_0p5_rounded = round(pt_0p5 * 4) / 4
        pt_2p0_rounded = round(pt_2p0 * 4) / 4
        sl_px_rounded = round(sl_px * 4) / 4
        
        # 1. Trace chronologically to see if +0.50 ATR was hit first
        touch_idx = -1
        for j in range(idx_start, idx_end + 1):
            h, l = h_1s[j], l_1s[j]
            # Check stop loss
            if (d == 1 and l <= sl_px_rounded) or (d == -1 and h >= sl_px_rounded):
                break
            # Check target +0.50 ATR
            if (d == 1 and h >= pt_0p5_rounded) or (d == -1 and l <= pt_0p5_rounded):
                touch_idx = j
                break
                
        if touch_idx == -1:
            # Stopped out or ended before hitting +0.50 ATR. Skip!
            continue
            
        # 2. This is the active cohort that successfully hit +0.50 ATR first!
        # Now trace from touch_idx to idx_end to find clean winner (+2.0 ATR) vs stopout (-1.5 ATR)
        pnl_type = "regime" # fallback
        for k in range(touch_idx, idx_end + 1):
            h, l = h_1s[k], l_1s[k]
            if (d == 1 and l <= sl_px_rounded) or (d == -1 and h >= sl_px_rounded):
                pnl_type = "stopout"
                break
            if (d == 1 and h >= pt_2p0_rounded) or (d == -1 and l <= pt_2p0_rounded):
                pnl_type = "winner"
                break
                
        # 3. Analyze the post-entry evolution metrics during the first 30 seconds
        limit_30s = min(idx_start + 30, len(ts_1s) - 1)
        sub_highs_30s = h_1s[idx_start:limit_30s+1]
        sub_lows_30s = l_1s[idx_start:limit_30s+1]
        
        if d == 1:
            mae_30s = entry_px - np.min(sub_lows_30s)
            mfe_30s = np.max(sub_highs_30s) - entry_px
            pnl_30s = c_1s[limit_30s] - entry_px
        else:
            mae_30s = np.max(sub_highs_30s) - entry_px
            mfe_30s = entry_px - np.min(sub_lows_30s)
            pnl_30s = entry_px - c_1s[limit_30s]
            
        mae_30s_atr = mae_30s / atr
        mfe_30s_atr = mfe_30s / atr
        pnl_30s_atr = pnl_30s / atr
        
        # 4. Analyze the post-entry evolution metrics during the first 60 seconds
        limit_60s = min(idx_start + 60, len(ts_1s) - 1)
        sub_highs_60s = h_1s[idx_start:limit_60s+1]
        sub_lows_60s = l_1s[idx_start:limit_60s+1]
        
        if d == 1:
            mae_60s = entry_px - np.min(sub_lows_60s)
            mfe_60s = np.max(sub_highs_60s) - entry_px
            pnl_60s = c_1s[limit_60s] - entry_px
        else:
            mae_60s = np.max(sub_highs_60s) - entry_px
            mfe_60s = entry_px - np.min(sub_lows_60s)
            pnl_60s = entry_px - c_1s[limit_60s]
            
        mae_60s_atr = mae_60s / atr
        mfe_60s_atr = mfe_60s / atr
        pnl_60s_atr = pnl_60s / atr
        
        # 5. VWAP z-abs causally at touch moment
        touch_ts = ts_1s[touch_idx]
        t_closed_open = (touch_ts // 60_000_000_000) * 60_000_000_000 - 60_000_000_000
        vwap_z_touch = vwap_z_dict.get(t_closed_open, 1.0)
        
        # Seconds taken to touch +0.50 ATR target
        sec_to_touch = (touch_ts - entry_ts) / 1_000_000_000
        
        active_cohort.append({
            "year": y,
            "direction": d,
            "atr": atr,
            "pnl_type": pnl_type,
            "mae_30s_atr": mae_30s_atr,
            "mfe_30s_atr": mfe_30s_atr,
            "pnl_30s_atr": pnl_30s_atr,
            "mae_60s_atr": mae_60s_atr,
            "mfe_60s_atr": mfe_60s_atr,
            "pnl_60s_atr": pnl_60s_atr,
            "vwap_z_touch": vwap_z_touch,
            "sec_to_touch": sec_to_touch
        })
        
    df_cohort = pd.DataFrame(active_cohort)
    print(f"\nActive Cohort (Trades hitting +0.50 ATR target first): {len(df_cohort)} out of 210.")
    print("Outcomes distribution:")
    print(df_cohort["pnl_type"].value_counts().to_string())
    
    # Filter for Winners and Stopouts
    winners = df_cohort[df_cohort["pnl_type"] == "winner"]
    stopouts = df_cohort[df_cohort["pnl_type"] == "stopout"]
    
    print(f"\nComparing {len(winners)} Clean Winners (+2.0 ATR) vs {len(stopouts)} Fakers/Reverters (-1.5 ATR):")
    
    metrics = [
        ("sec_to_touch", "Seconds to touch +0.50 ATR"),
        ("mae_30s_atr", "Max Adverse Excursion in first 30s (ATR)"),
        ("mfe_30s_atr", "Max Favorable Excursion in first 30s (ATR)"),
        ("pnl_30s_atr", "PnL at 30s (ATR)"),
        ("mae_60s_atr", "Max Adverse Excursion in first 60s (ATR)"),
        ("mfe_60s_atr", "Max Favorable Excursion in first 60s (ATR)"),
        ("pnl_60s_atr", "PnL at 60s (ATR)"),
        ("vwap_z_touch", "VWAP distance at +0.50 ATR touch moment")
    ]
    
    print("\n" + "-"*90)
    print(f"  {'Metric Description':<40} | {'Winners Mean':^14} | {'Stopouts Mean':^14} | {'Diff':^10}")
    print("-"*90)
    for col, desc in metrics:
        w_mean = winners[col].mean()
        s_mean = stopouts[col].mean()
        diff = w_mean - s_mean
        print(f"  {desc:<40} | {w_mean:>12.4f}   | {s_mean:>12.4f}   | {diff:>+8.4f}")
    print("-"*90)
    
    # Let's perform a key threshold analysis!
    # Can we find a simple post-entry rule that isolates losers?
    # What if mae_30s_atr is large?
    print("\nThreshold Analysis: Is a deep pullback in the first 30s a sign of a reverter?")
    for thresh in [0.10, 0.20, 0.30, 0.40]:
        high_pullback_cohort = df_cohort[df_cohort["mae_30s_atr"] >= thresh]
        low_pullback_cohort = df_cohort[df_cohort["mae_30s_atr"] < thresh]
        
        hp_winners = (high_pullback_cohort["pnl_type"] == "winner").sum()
        hp_stopouts = (high_pullback_cohort["pnl_type"] == "stopout").sum()
        hp_ratio = hp_winners / (hp_winners + hp_stopouts) * 100 if (hp_winners + hp_stopouts) > 0 else 0.0
        
        lp_winners = (low_pullback_cohort["pnl_type"] == "winner").sum()
        lp_stopouts = (low_pullback_cohort["pnl_type"] == "stopout").sum()
        lp_ratio = lp_winners / (lp_winners + lp_stopouts) * 100 if (lp_winners + lp_stopouts) > 0 else 0.0
        
        print(f"  Adverse pullback in first 30s >= {thresh:.2f} ATR:")
        print(f"    Yes (n={len(high_pullback_cohort)}): Winners={hp_winners}, Stopouts={hp_stopouts} | Win Ratio: {hp_ratio:.1f}%")
        print(f"    No  (n={len(low_pullback_cohort)}): Winners={lp_winners}, Stopouts={lp_stopouts} | Win Ratio: {lp_ratio:.1f}%")
        
    print("\nThreshold Analysis: What if NQ PnL at 30s is already negative/weak?")
    for thresh in [0.0, 0.10, 0.20]:
        weak_30s_cohort = df_cohort[df_cohort["pnl_30s_atr"] < thresh]
        strong_30s_cohort = df_cohort[df_cohort["pnl_30s_atr"] >= thresh]
        
        w_winners = (weak_30s_cohort["pnl_type"] == "winner").sum()
        w_stopouts = (weak_30s_cohort["pnl_type"] == "stopout").sum()
        w_ratio = w_winners / (w_winners + w_stopouts) * 100 if (w_winners + w_stopouts) > 0 else 0.0
        
        s_winners = (strong_30s_cohort["pnl_type"] == "winner").sum()
        s_stopouts = (strong_30s_cohort["pnl_type"] == "stopout").sum()
        s_ratio = s_winners / (s_winners + s_stopouts) * 100 if (s_winners + s_stopouts) > 0 else 0.0
        
        print(f"  Trade PnL at 30s < {thresh:.2f} ATR:")
        print(f"    Yes (n={len(weak_30s_cohort)}): Winners={w_winners}, Stopouts={w_stopouts} | Win Ratio: {w_ratio:.1f}%")
        print(f"    No  (n={len(strong_30s_cohort)}): Winners={s_winners}, Stopouts={s_stopouts} | Win Ratio: {s_ratio:.1f}%")
        
    # Save results for report
    df_cohort.to_parquet("scratch/post_entry_evolution_results.parquet")
    print(f"\nResults saved to scratch/post_entry_evolution_results.parquet.")

if __name__ == "__main__":
    main()
