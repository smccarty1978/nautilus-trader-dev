import pandas as pd
import numpy as np
import os
from sklearn.preprocessing import StandardScaler
from sklearn.cluster import MiniBatchKMeans

def run_simulation(pop, bars_cache, entry_anchor, sl_atr_val):
    results_list = []
    
    for idx, row in pop.iterrows():
        y = int(row["year"])
        bars = bars_cache[y]
        ts_1s = bars.index.astype("int64").to_numpy()
        h_1s = bars["high"].to_numpy()
        l_1s = bars["low"].to_numpy()
        c_1s = bars["close"].to_numpy()
        
        if entry_anchor == "bar1_confirm":
            entry_ts = int(row["entry_ts"]) + 60 * 1_000_000_000
            entry_px = float(row["entry_px_bar1"])
        else:
            entry_ts = int(row["entry_ts"])
            entry_px = float(row["entry_px"])
            
        atr = float(row["entry_atr"])
        d = int(row["signal_direction"])
        exit_ts_regime = int(row["exit_ts"])
        exit_px_regime = float(row["exit_px"])
        
        idx_start = np.searchsorted(ts_1s, entry_ts, side="left")
        idx_end = np.searchsorted(ts_1s, exit_ts_regime, side="right") - 1
        idx_end = max(idx_start, min(idx_end, len(ts_1s) - 1))
        
        # We sweep the initial stop loss
        sl_px = entry_px - d * sl_atr_val * atr
        pt_0p5 = entry_px + d * 0.50 * atr
        pt_2p0 = entry_px + d * 2.00 * atr
        
        sl_px_rounded = round(sl_px * 4) / 4
        pt_0p5_rounded = round(pt_0p5 * 4) / 4
        pt_2p0_rounded = round(pt_2p0 * 4) / 4
        
        # Gate Strategy (Speed Gate + 60s PnL Gate + tight initial SL)
        exit_px_c1_gate = None
        exit_px_c2_gate = None
        c1_reason = ""
        c2_reason = ""
        
        # Find first touch of SL or PT1
        touch_idx = -1
        for j in range(idx_start, idx_end + 1):
            h, l = h_1s[j], l_1s[j]
            if (d == 1 and l <= sl_px_rounded) or (d == -1 and h >= sl_px_rounded):
                exit_px_c1_gate = exit_px_c2_gate = sl_px_rounded
                c1_reason = c2_reason = "stop_loss"
                break
            if (d == 1 and h >= pt_0p5_rounded) or (d == -1 and l <= pt_0p5_rounded):
                touch_idx = j
                break
                
        if touch_idx == -1 and exit_px_c1_gate is None:
            exit_px_c1_gate = exit_px_c2_gate = exit_px_regime
            c1_reason = c2_reason = "regime_exit"
            
        elif touch_idx != -1:
            exit_px_c1_gate = pt_0p5_rounded
            c1_reason = "PT1"
            
            sec_to_touch = (ts_1s[touch_idx] - entry_ts) / 1_000_000_000
            
            if sec_to_touch < 30.0:
                exit_px_c2_gate = pt_0p5_rounded
                c2_reason = "SpeedGate_exhaustion"
            else:
                exit_px_c2_gate = exit_px_regime
                c2_reason = "regime_exit"
                
                gate_60s_ts = entry_ts + 60 * 1_000_000_000
                
                for k in range(touch_idx + 1, idx_end + 1):
                    h, l, c = h_1s[k], l_1s[k], c_1s[k]
                    t_curr = ts_1s[k]
                    
                    if t_curr >= gate_60s_ts:
                        pnl_60s = (c - entry_px) * d
                        if pnl_60s < 0.30 * atr:
                            exit_px_c2_gate = c
                            c2_reason = "Gate_60s_exhaustion"
                            break
                            
                    if (d == 1 and l <= sl_px_rounded) or (d == -1 and h >= sl_px_rounded):
                        exit_px_c2_gate = sl_px_rounded
                        c2_reason = "stop_loss"
                        break
                        
                    if (d == 1 and h >= pt_2p0_rounded) or (d == -1 and l <= pt_2p0_rounded):
                        exit_px_c2_gate = pt_2p0_rounded
                        c2_reason = "PT2"
                        break
                        
        pnl_gate = (exit_px_c1_gate - entry_px) * d + (exit_px_c2_gate - entry_px) * d
        
        results_list.append({
            "year": y,
            "pnl_gate_pts": pnl_gate,
            "c2_reason": c2_reason
        })
        
    df_results = pd.DataFrame(results_list)
    return df_results

def main():
    df_ex = pd.read_parquet("studies/regime_classification/results/flips_excursion_paths.parquet")
    
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
    
    bars_cache = {}
    for y in [2023, 2024, 2025, 2026]:
        p = f"data/raw/NQ_v0_1s_{y}.parquet" if y != 2026 else "data/raw/NQ_v0_1s_2026_ytd.parquet"
        if os.path.exists(p):
            df_bars = pd.read_parquet(p, columns=["high", "low", "close"])
            if df_bars.index.tz is None:
                df_bars.index = df_bars.index.tz_localize("UTC")
            bars_cache[y] = df_bars
            
    for anchor in ["bar1_confirm", "ancflip"]:
        if anchor == "bar1_confirm":
            pop = df_ex[(df_ex["year"].isin((2023, 2024, 2025, 2026))) & 
                        (df_ex["kmeans_static_aligned"] == 0) & 
                        (df_ex["entry_atr"] > 15.0) & 
                        (df_ex["bar1_confirm"] == True)].copy()
        else:
            pop = df_ex[(df_ex["year"].isin((2023, 2024, 2025, 2026))) & 
                        (df_ex["kmeans_static_aligned"] == 0) & 
                        (df_ex["entry_atr"] > 15.0)].copy()
                        
        print("\n" + "="*120)
        print(f"  SIMULATING SPEED GATE + 60S CAUSAL PN_L GATE WITH TIGHT INITIAL SL ({anchor.upper()})")
        print("="*120)
        
        # Let's sweep the initial stop loss: 0.50 ATR, 0.75 ATR, 1.00 ATR, 1.50 ATR
        for sl_atr in [0.50, 0.75, 1.00, 1.50]:
            df_sim = run_simulation(pop, bars_cache, anchor, sl_atr)
            df_sim["gate_net_usd"] = df_sim["pnl_gate_pts"] * 20.0 - 20.0
            
            pnl_sum = df_sim["gate_net_usd"].sum()
            wins = df_sim[df_sim["gate_net_usd"] > 0]["gate_net_usd"].sum()
            losses = df_sim[df_sim["gate_net_usd"] < 0]["gate_net_usd"].sum()
            pf = wins / abs(losses) if losses != 0 else np.nan
            
            # Print by year
            y_pnls = {}
            for y in [2023, 2024, 2025, 2026]:
                y_pnls[y] = df_sim[df_sim["year"] == y]["gate_net_usd"].sum()
                
            print(f"  Initial SL: {sl_atr:.2f} ATR | Overall PnL = ${pnl_sum:>+10,.2f} | PF = {pf:.2f}")
            print(f"    Yearly breakdown: 2023: ${y_pnls[2023]:>+9,.2f} | 2024: ${y_pnls[2024]:>+9,.2f} | 2025: ${y_pnls[2025]:>+9,.2f} | 2026: ${y_pnls[2026]:>+9,.2f}")
            
if __name__ == "__main__":
    main()
