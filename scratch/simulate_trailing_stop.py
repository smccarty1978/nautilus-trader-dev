"""Simulate Trailing Stop / Break-Even overlays on 1s high-fidelity NQ paths

Simulates:
1. Standard bracket (PT / SL) with terminal time-exit.
2. Break-even stop trigger: once price reaches BE_trigger * ATR, the stop-loss is moved to BE_level * ATR (typically 0.0).
3. Evaluates Net EV and Profit Factor net of $10 friction separately for Good Years (24/25) and Bad Years (23/26).
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
def simulate_trade_path(px_entry, atr, d, ts_start, ts_1s, high_1s, low_1s, close_1s, index_entry,
                        pt_atr, sl_atr, be_trigger_atr, be_level_atr):
    """Simulates a single trade's path in 1-second resolution, applying the break-even trailing stop."""
    j = index_entry
    pt_px = pt_atr * atr
    sl_px = -sl_atr * atr
    be_trig_px = be_trigger_atr * atr
    be_stop_px = be_level_atr * atr
    
    current_stop_px = sl_px
    peak_mfe = 0.0
    be_activated = False
    
    # Outcomes
    # 1 = PT hit, -1 = SL hit, 0 = Time exit
    outcome = 0
    realized_change_px = 0.0
    
    while j < len(ts_1s):
        dt = ts_1s[j] - ts_start
        if dt > 60 * 1_000_000_000:
            break
            
        h, l, c = high_1s[j], low_1s[j], close_1s[j]
        
        # Calculate excursions in this bar relative to entry
        if d == 1:
            mfe_bar = h - px_entry
            mae_bar = l - px_entry  # negative change represents adverse excursion
            close_rel = c - px_entry
        else:
            mfe_bar = px_entry - l
            mae_bar = px_entry - h  # negative change represents adverse excursion
            close_rel = px_entry - c
            
        # 1. Check if we hit the stop loss in this bar
        # For a stop-loss, we check if the adverse excursion (mae_bar) is worse (more negative) than current_stop_px
        if mae_bar <= current_stop_px:
            # We got stopped out!
            outcome = -1
            realized_change_px = current_stop_px
            break
            
        # 2. Check if we hit the profit target in this bar
        if mfe_bar >= pt_px:
            # We hit target!
            outcome = 1
            realized_change_px = pt_px
            break
            
        # 3. Update the break-even stop trigger
        if mfe_bar > peak_mfe:
            peak_mfe = mfe_bar
            
        if peak_mfe >= be_trig_px and not be_activated:
            be_activated = True
            current_stop_px = be_stop_px
            
        j += 1
        
    if outcome == 0 and j > index_entry:
        # Time exit at terminal close
        last_idx = min(j - 1, len(ts_1s) - 1)
        c = close_1s[last_idx]
        if d == 1:
            close_rel = c - px_entry
        else:
            close_rel = px_entry - c
        realized_change_px = close_rel
        
    return outcome, realized_change_px / atr


@njit
def run_simulation_sweep(entry_ts_arr, entry_px_arr, entry_atr_arr, dir_arr,
                         ts_1s, high_1s, low_1s, close_1s,
                         pt_atr, sl_atr, be_trigger_atr, be_level_atr):
    N = len(entry_ts_arr)
    outcomes = np.zeros(N, dtype=np.int8)
    realized_atr_pnl = np.zeros(N, dtype=np.float64)
    
    indices = np.searchsorted(ts_1s, entry_ts_arr, side="left")
    
    for i in range(N):
        idx_entry = indices[i]
        if idx_entry >= len(ts_1s) or entry_atr_arr[i] <= 0:
            continue
            
        px_entry = entry_px_arr[i]
        atr = entry_atr_arr[i]
        d = dir_arr[i]
        ts_start = entry_ts_arr[i]
        
        outcome, pnl_atr = simulate_trade_path(
            px_entry, atr, d, ts_start, ts_1s, high_1s, low_1s, close_1s, idx_entry,
            pt_atr, sl_atr, be_trigger_atr, be_level_atr
        )
        
        outcomes[i] = outcome
        realized_atr_pnl[i] = pnl_atr
        
    return outcomes, realized_atr_pnl


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
    
    # 1. Load triggers
    df_ex = pd.read_parquet("studies/regime_classification/results/flips_excursion_paths.parquet")
    print(f"Loaded {len(df_ex):,} flips.")
    
    # Load 1s data and align states (same as prior studies)
    all_years_df = []
    bars_cache = {}
    for y in sorted(df_ex["year"].unique()):
        year_cohort = df_ex[df_ex["year"] == y].copy()
        if len(year_cohort) == 0:
            continue
        try:
            bars = load_1s(y)
            bars_cache[y] = bars
        except FileNotFoundError:
            continue
        all_years_df.append(year_cohort)
        
    df_flips = pd.concat(all_years_df, ignore_index=True)
    
    # Load static states
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
    
    # Filter to State 0 + ATR > 15 in OOS (2023-2026)
    pop = df_flips[(df_flips["year"].isin((2023, 2024, 2025, 2026))) & 
                   (df_flips["kmeans_static_aligned"] == 0) & 
                   (df_flips["entry_atr"] > 15.0)].copy()
    
    # Run the trailing stop simulation sweeps
    # We want to test different combinations:
    # PT: 0.5, 0.6, 0.8
    # SL: 1.5, 2.0
    # BE Trigger: None (standard), 0.25, 0.30, 0.40
    
    PT_LIST = [0.5, 0.6, 0.8]
    SL_LIST = [1.5, 2.0]
    BE_TRIGGERS = [999.0, 0.25, 0.30, 0.40]
    BE_LEVELS = [0.0, -0.25, -0.50]
    
    results = []
    
    # Group triggers by year for fast simulation
    for pt in PT_LIST:
        for sl in SL_LIST:
            for be_trig in BE_TRIGGERS:
                levels_to_sweep = [0.0] if be_trig > 900.0 else BE_LEVELS
                for be_level in levels_to_sweep:
                    all_sim_pnl = []
                    
                    for y in sorted(pop["year"].unique()):
                        year_pop = pop[pop["year"] == y].copy()
                        if len(year_pop) == 0:
                            continue
                        bars = bars_cache[y]
                        ts_1s = bars.index.astype("int64").to_numpy()
                        h_1s = bars["high"].to_numpy(np.float64)
                        l_1s = bars["low"].to_numpy(np.float64)
                        c_1s = bars["close"].to_numpy(np.float64)
                        
                        outcomes, realized_pnl = run_simulation_sweep(
                            year_pop["entry_ts"].to_numpy(np.int64),
                            year_pop["entry_px"].to_numpy(np.float64),
                            year_pop["entry_atr"].to_numpy(np.float64),
                            year_pop["signal_direction"].to_numpy(np.int64),
                            ts_1s, h_1s, l_1s, c_1s,
                            pt, sl, be_trig, be_level
                        )
                        
                        year_pop["sim_outcome"] = outcomes
                        year_pop["sim_pnl_atr"] = realized_pnl
                        all_sim_pnl.append(year_pop)
                        
                    df_sim = pd.concat(all_sim_pnl, ignore_index=True)
                    
                    # Compute PnL
                    df_sim["gross_pnl"] = df_sim["sim_pnl_atr"] * df_sim["entry_atr"] * 20.0
                    df_sim["net_pnl"] = df_sim["gross_pnl"] - 10.0
                    
                    win_cohort = df_sim[df_sim["year"].isin((2024, 2025))]
                    bad_cohort = df_sim[df_sim["year"].isin((2023, 2026))]
                    
                    def get_stats(df):
                        tot_net = df["net_pnl"].sum()
                        wins = df[df["net_pnl"] > 0]["net_pnl"].sum()
                        losses = df[df["net_pnl"] < 0]["net_pnl"].sum()
                        pf = wins / abs(losses) if losses != 0 else np.nan
                        win_rate = (df["sim_outcome"] == 1).mean() * 100
                        loss_rate = (df["sim_outcome"] == -1).mean() * 100
                        flat_rate = (df["sim_outcome"] == 0).mean() * 100
                        return tot_net, pf, win_rate, loss_rate, flat_rate
                    
                    w_net, w_pf, w_win, w_loss, w_flat = get_stats(win_cohort)
                    b_net, b_pf, b_win, b_loss, b_flat = get_stats(bad_cohort)
                    
                    results.append({
                        "PT": pt, "SL": sl, "BE_Trig": be_trig, "BE_Level": be_level,
                        "W_Net": w_net, "W_PF": w_pf, "W_Win%": w_win, "W_Loss%": w_loss, "W_Flat%": w_flat,
                        "B_Net": b_net, "B_PF": b_pf, "B_Win%": b_win, "B_Loss%": b_loss, "B_Flat%": b_flat,
                        "Total_Net": w_net + b_net
                    })
                    
    df_res = pd.DataFrame(results)
    
    print("\n" + "="*130)
    print("  SIMULATION RESULTS: PT / SL BRACKETS WITH BREAK-EVEN TRAILING STOP (BREATHING ROOM SWEEP)")
    print("="*130)
    print(f"  {'PT':<4} {'SL':<4} {'BE Trig':<8} {'BE Lvl':<6} | {'Good Years (2024/2025)':^32} | {'Bad Years (2023/2026)':^32} | {'Total Net':>12}")
    print(f"  {'':<4} {'':<4} {'':<8} {'':<6} | {'Net PnL':>10} {'PF':>6} {'Win%':>6} {'Loss%':>6} | {'Net PnL':>10} {'PF':>6} {'Win%':>6} {'Loss%':>6} | {'PnL':>12}")
    print("  " + "-"*126)
    
    for _, row in df_res.sort_values(by="Total_Net", ascending=False).iterrows():
        be_str = "None" if row["BE_Trig"] > 900.0 else f"+{row['BE_Trig']:.2f}"
        lvl_str = "N/A" if row["BE_Trig"] > 900.0 else f"{row['BE_Level']:+.2f}"
        print(f"  {row['PT']:<4.1f} {row['SL']:<4.1f} {be_str:<8} {lvl_str:<6} | "
              f"{row['W_Net']:>+10.2f}$ {row['W_PF']:>6.2f} {row['W_Win%']:>5.1f}% {row['W_Loss%']:>5.1f}% | "
              f"{row['B_Net']:>+10.2f}$ {row['B_PF']:>6.2f} {row['B_Win%']:>5.1f}% {row['B_Loss%']:>5.1f}% | "
              f"{row['Total_Net']:>+12.2f}$")
              
    print(f"\n[done] {(time.time()-t0)/60:.2f} min")


if __name__ == "__main__":
    main()
