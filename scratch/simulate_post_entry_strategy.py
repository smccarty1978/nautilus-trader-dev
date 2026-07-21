import pandas as pd
import numpy as np
import os
from sklearn.preprocessing import StandardScaler
from sklearn.cluster import MiniBatchKMeans

def run_simulation(pop, bars_cache, entry_anchor):
    results_list = []
    
    # Sweep configurations:
    # 1. Baseline: PT1=0.5 ATR, SL=1.5 ATR (Negative Asymmetric Baseline)
    # 2. Gate Strategy: Speed Gate + 60s PnL Gate
    
    for idx, row in pop.iterrows():
        y = int(row["year"])
        bars = bars_cache[y]
        ts_1s = bars.index.astype("int64").to_numpy()
        h_1s = bars["high"].to_numpy()
        l_1s = bars["low"].to_numpy()
        c_1s = bars["close"].to_numpy()
        
        # entry ts and px depends on anchor
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
        
        sl_px = entry_px - d * 1.50 * atr
        pt_0p5 = entry_px + d * 0.50 * atr
        pt_2p0 = entry_px + d * 2.00 * atr
        
        # Round target/stops to nearest tick
        sl_px_rounded = round(sl_px * 4) / 4
        pt_0p5_rounded = round(pt_0p5 * 4) / 4
        pt_2p0_rounded = round(pt_2p0 * 4) / 4
        
        # ── Setup 1: Baseline (PT 0.50 ATR / SL 1.50 ATR, 2 contracts) ──
        # Contract 1 exits at PT 0.50 or SL. Contract 2 exits at PT 0.50 or SL.
        exit_px_c1_base = None
        exit_px_c2_base = None
        
        for j in range(idx_start, idx_end + 1):
            h, l = h_1s[j], l_1s[j]
            if (d == 1 and l <= sl_px_rounded) or (d == -1 and h >= sl_px_rounded):
                exit_px_c1_base = exit_px_c2_base = sl_px_rounded
                break
            if (d == 1 and h >= pt_0p5_rounded) or (d == -1 and l <= pt_0p5_rounded):
                exit_px_c1_base = exit_px_c2_base = pt_0p5_rounded
                break
                
        if exit_px_c1_base is None:
            exit_px_c1_base = exit_px_c2_base = exit_px_regime
            
        pnl_base = (exit_px_c1_base - entry_px) * d + (exit_px_c2_base - entry_px) * d
        
        # ── Setup 2: Gate Strategy (Speed Gate + 60s PnL Gate) ──
        exit_px_c1_gate = None
        exit_px_c2_gate = None
        c1_reason = ""
        c2_reason = ""
        
        # Find first touch of SL or PT1
        touch_idx = -1
        for j in range(idx_start, idx_end + 1):
            h, l = h_1s[j], l_1s[j]
            if (d == 1 and l <= sl_px_rounded) or (d == -1 and h >= sl_px_rounded):
                # Stopped out before hitting PT1
                exit_px_c1_gate = exit_px_c2_gate = sl_px_rounded
                c1_reason = c2_reason = "stop_loss"
                break
            if (d == 1 and h >= pt_0p5_rounded) or (d == -1 and l <= pt_0p5_rounded):
                # Touched PT1 target!
                touch_idx = j
                break
                
        if touch_idx == -1 and exit_px_c1_gate is None:
            # Reached regime close without hitting SL or PT1
            exit_px_c1_gate = exit_px_c2_gate = exit_px_regime
            c1_reason = c2_reason = "regime_exit"
            
        elif touch_idx != -1:
            # Touched PT1 first! Fill Contract 1 at exactly PT1 price
            exit_px_c1_gate = pt_0p5_rounded
            c1_reason = "PT1"
            
            # Check Speed Gate:
            sec_to_touch = (ts_1s[touch_idx] - entry_ts) / 1_000_000_000
            
            if sec_to_touch < 30.0:
                # Fast Spike! Speed Gate triggers. Close runner instantly at PT1 price
                exit_px_c2_gate = pt_0p5_rounded
                c2_reason = "SpeedGate_exhaustion"
            else:
                # Grinding breakout! Let runner contract continue
                # Search chronologically for SL or PT2 or 60s gate
                exit_px_c2_gate = exit_px_regime # fallback
                c2_reason = "regime_exit"
                
                # We also need to identify the exact bar index corresponding to entry_ts + 60s
                gate_60s_ts = entry_ts + 60 * 1_000_000_000
                
                for k in range(touch_idx + 1, idx_end + 1):
                    h, l, c = h_1s[k], l_1s[k], c_1s[k]
                    t_curr = ts_1s[k]
                    
                    # Check 60s Causal Gate
                    if t_curr >= gate_60s_ts:
                        # Evaluate trade PnL at 60s close
                        pnl_60s = (c - entry_px) * d
                        if pnl_60s < 0.30 * atr:
                            # Stalled expansion! Kill runner at market close price
                            exit_px_c2_gate = c
                            c2_reason = "Gate_60s_exhaustion"
                            break
                            
                    # Check SL
                    if (d == 1 and l <= sl_px_rounded) or (d == -1 and h >= sl_px_rounded):
                        exit_px_c2_gate = sl_px_rounded
                        c2_reason = "stop_loss"
                        break
                        
                    # Check PT2
                    if (d == 1 and h >= pt_2p0_rounded) or (d == -1 and l <= pt_2p0_rounded):
                        exit_px_c2_gate = pt_2p0_rounded
                        c2_reason = "PT2"
                        break
                        
        pnl_gate = (exit_px_c1_gate - entry_px) * d + (exit_px_c2_gate - entry_px) * d
        
        results_list.append({
            "year": y,
            "pnl_base_pts": pnl_base,
            "pnl_gate_pts": pnl_gate,
            "c2_reason": c2_reason
        })
        
    df_results = pd.DataFrame(results_list)
    return df_results

def main():
    # 1. Load flips and align Macro states
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
    
    # 2. Load 1s data
    bars_cache = {}
    for y in [2023, 2024, 2025, 2026]:
        p = f"data/raw/NQ_v0_1s_{y}.parquet" if y != 2026 else "data/raw/NQ_v0_1s_2026_ytd.parquet"
        if os.path.exists(p):
            df_bars = pd.read_parquet(p, columns=["high", "low", "close"])
            if df_bars.index.tz is None:
                df_bars.index = df_bars.index.tz_localize("UTC")
            bars_cache[y] = df_bars
            
    # 3. Simulate both anchors!
    for anchor in ["bar1_confirm", "ancflip"]:
        # Filter cohort
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
        print(f"  SIMULATING SPEED GATE + 60S CAUSAL PN_L GATE FOR ANCHOR: {anchor.upper()}")
        print(f"  Active population size: {len(pop)} triggers | Sizing: 2 NQ Contracts ($20/point per contract)")
        print("="*120)
        
        df_sim = run_simulation(pop, bars_cache, anchor)
        
        # Calculate expected values and sum PnL
        # Apply $10 friction per contract ($20 total per trade)
        df_sim["base_net_usd"] = df_sim["pnl_base_pts"] * 20.0 - 20.0
        df_sim["gate_net_usd"] = df_sim["pnl_gate_pts"] * 20.0 - 20.0
        
        # Calculate PF for baseline vs gate
        def get_pstats(df_cohort):
            base_pnl = df_cohort["base_net_usd"].sum()
            gate_pnl = df_cohort["gate_net_usd"].sum()
            
            base_wins = df_cohort[df_cohort["base_net_usd"] > 0]["base_net_usd"].sum()
            base_losses = df_cohort[df_cohort["base_net_usd"] < 0]["base_net_usd"].sum()
            base_pf = base_wins / abs(base_losses) if base_losses != 0 else np.nan
            
            gate_wins = df_cohort[df_cohort["gate_net_usd"] > 0]["gate_net_usd"].sum()
            gate_losses = df_cohort[df_cohort["gate_net_usd"] < 0]["gate_net_usd"].sum()
            gate_pf = gate_wins / abs(gate_losses) if gate_losses != 0 else np.nan
            
            return base_pnl, base_pf, gate_pnl, gate_pf
            
        b_pnl, b_pf, g_pnl, g_pf = get_pstats(df_sim)
        print(f"\nOverall OOS (2023-2026):")
        print(f"  Baseline 0.5 PT / 1.5 SL  : Net PnL = ${b_pnl:,.2f} | Profit Factor = {b_pf:.2f}")
        print(f"  Speed + 60s Causal Gate   : Net PnL = ${g_pnl:,.2f} | Profit Factor = {g_pf:.2f}")
        
        print("\nYear-by-Year Performance Breakdown (Net PnL in $):")
        print(f"  {'Year':<4} | {'Baseline Net PnL':^18} {'Baseline PF':^11} | {'Gate Net PnL':^18} {'Gate PF':^11}")
        print("  " + "-" * 70)
        for y in [2023, 2024, 2025, 2026]:
            y_df = df_sim[df_sim["year"] == y]
            yb_pnl, yb_pf, yg_pnl, yg_pf = get_pstats(y_df)
            print(f"  {y:<4} | {yb_pnl:>+14.2f}$  {yb_pf:>8.2f}  | {yg_pnl:>+14.2f}$  {yg_pf:>8.2f}")
            
        print("\nExit reason counts on Gate runner contract (Contract 2):")
        print(df_sim["c2_reason"].value_counts().to_string())

if __name__ == "__main__":
    main()
