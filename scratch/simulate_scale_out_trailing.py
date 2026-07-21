"""Simulate Split-Size Trailing Stop / Scale-Out / EMA Trailing exits on 1s high-fidelity NQ paths

Simulates:
- A: PT 0.50 ATR / SL 1.50 ATR (pure static bracket)
- B: 50% off at 0.50 ATR / runner to regime exit
- C: 50% off at 0.50 ATR / BE stop / runner to regime exit
- D: 50% off at 0.50 ATR / trail runner behind 1m EMA9 Close
- E: 50% off at 0.50 ATR / trail runner behind 1m EMA13 Close

All trades are simulated on the State 0 + ATR > 15 OOS population (2023-2026).
Starting size is 2 contracts (Contract 1 and Contract 2, each 1 contract size).
Strict $10 per-contract transaction friction is applied ($20 total per trade).
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
    print(f"OOS Population size: {len(pop)} trades.")
    
    # Pre-calculate 1m EMA9 and EMA13 closes for OOS years
    ema9_caches = {}
    ema13_caches = {}
    for y in sorted(pop["year"].unique()):
        bars = bars_cache[y]
        # Resample 1s to 1m, forward fill gaps
        bars_1m = bars["close"].resample("1Min", label="right").last().ffill()
        ema9 = bars_1m.ewm(span=9, adjust=False).mean()
        ema13 = bars_1m.ewm(span=13, adjust=False).mean()
        
        # Build nanosecond key lookup dicts
        ema9_caches[y] = {ts.value: val for ts, val in ema9.items()}
        ema13_caches[y] = {ts.value: val for ts, val in ema13.items()}
        print(f"Year {y}: Calculated {len(bars_1m)} 1m close and EMA bars.")

    # Simulation logic
    def run_split_simulation(strategy_name):
        results_list = []
        for _, row in pop.iterrows():
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
            
            # Use the actual flip regime exit from the trigger parquet
            exit_ts_regime = int(row["exit_ts"])
            exit_px_regime = float(row["exit_px"])
            
            # Find the slice of 1s bars
            idx_start = np.searchsorted(ts_1s, entry_ts, side="left")
            idx_end = np.searchsorted(ts_1s, exit_ts_regime, side="right") - 1
            idx_end = max(idx_start, min(idx_end, len(ts_1s) - 1))
            
            # Target and stop prices
            pt_atr_level = 0.50
            sl_atr_level = 1.50
            pt_px = entry_px + d * pt_atr_level * atr
            sl_px = entry_px - d * sl_atr_level * atr
            
            # Contract 1: PT 0.50 ATR, SL 1.50 ATR, falls back to regime exit
            exit_px_c1 = None
            for j in range(idx_start, idx_end + 1):
                h, l = h_1s[j], l_1s[j]
                # Check stop hit
                if (d == 1 and l <= sl_px) or (d == -1 and h >= sl_px):
                    exit_px_c1 = sl_px
                    break
                # Check target hit
                if (d == 1 and h >= pt_px) or (d == -1 and l <= pt_px):
                    exit_px_c1 = pt_px
                    break
            if exit_px_c1 is None:
                exit_px_c1 = exit_px_regime
                
            # Contract 2: depends on strategy
            exit_px_c2 = None
            
            if strategy_name == "A":
                # Identical to Contract 1
                exit_px_c2 = exit_px_c1
                
            elif strategy_name == "B":
                # SL 1.50 ATR, exits at regime exit (no PT)
                for j in range(idx_start, idx_end + 1):
                    h, l = h_1s[j], l_1s[j]
                    if (d == 1 and l <= sl_px) or (d == -1 and h >= sl_px):
                        exit_px_c2 = sl_px
                        break
                if exit_px_c2 is None:
                    exit_px_c2 = exit_px_regime
                    
            elif strategy_name == "C":
                # BE stop on target hit
                target_hit = False
                for j in range(idx_start, idx_end + 1):
                    h, l = h_1s[j], l_1s[j]
                    # Check if target hit to activate BE
                    if not target_hit:
                        if (d == 1 and h >= pt_px) or (d == -1 and l <= pt_px):
                            target_hit = True
                    
                    active_sl = entry_px if target_hit else sl_px
                    if (d == 1 and l <= active_sl) or (d == -1 and h >= active_sl):
                        exit_px_c2 = active_sl
                        break
                if exit_px_c2 is None:
                    exit_px_c2 = exit_px_regime
                    
            elif strategy_name in ("D", "E"):
                # D: Trail EMA9 Close, E: Trail EMA13 Close
                ema_cache = ema9_caches[y] if strategy_name == "D" else ema13_caches[y]
                stop_px = sl_px
                last_min = -1
                
                for j in range(idx_start, idx_end + 1):
                    ts = ts_1s[j]
                    h, l = h_1s[j], l_1s[j]
                    
                    # Update trailing stop on 1m bar close
                    curr_min = ts // 60_000_000_000
                    if curr_min > last_min:
                        if last_min != -1:
                            t_close = curr_min * 60_000_000_000
                            ema_val = ema_cache.get(t_close, None)
                            if ema_val is not None:
                                if d == 1:
                                    stop_px = max(stop_px, ema_val)
                                else:
                                    stop_px = min(stop_px, ema_val)
                        last_min = curr_min
                        
                    # Check stop hit
                    if (d == 1 and l <= stop_px) or (d == -1 and h >= stop_px):
                        exit_px_c2 = stop_px
                        break
                if exit_px_c2 is None:
                    exit_px_c2 = exit_px_regime
            
            # PnL in points
            p1 = (exit_px_c1 - entry_px) * d
            p2 = (exit_px_c2 - entry_px) * d
            
            # Apply $10 friction per contract ($20 total per trade)
            gross1 = p1 * 20.0
            gross2 = p2 * 20.0
            net1 = gross1 - 10.0
            net2 = gross2 - 10.0
            total_net = net1 + net2
            
            results_list.append({
                "year": y,
                "net1": net1,
                "net2": net2,
                "total_net": total_net
            })
            
        df_sim = pd.DataFrame(results_list)
        return df_sim

    STRATEGIES = ["A", "B", "C", "D", "E"]
    sim_dfs = {}
    for s in STRATEGIES:
        print(f"Simulating Strategy {s}...")
        sim_dfs[s] = run_split_simulation(s)
        
    print("\n" + "="*120)
    print("  SCALE-OUT & TRAILING STOP STUDY: MULTI-CONTRACT HIGH-FIDELITY SIMULATION (OOS 2023-2026)")
    print("  Sizing: 2 Contracts starting | Contract 1: PT 0.50 ATR, SL 1.50 ATR | Friction: $10/contract ($20 total)")
    print("="*120)
    
    # Prepare comparison tables
    # 1. Overall stats
    print(f"  {'Strategy':<10} | {'Trades':>6} | {'Good Years (24/25)':^24} | {'Bad Years (23/26)':^24} | {'Total OOS Net':>16} | {'PF':>6}")
    print(f"  {'-'*10} | {'-'*6} | {'Net PnL':>10} {'Win%':>6} {'PF':>6} | {'Net PnL':>10} {'Win%':>6} {'PF':>6} | {'PnL ($)':>16} | {'-'*6}")
    
    for s in STRATEGIES:
        df = sim_dfs[s]
        
        good = df[df["year"].isin((24, 2024, 25, 2025))]
        bad = df[df["year"].isin((23, 2023, 26, 2026))]
        
        def get_cohort_stats(cohort):
            tot = cohort["total_net"].sum()
            win_rate = (cohort["total_net"] > 0).mean() * 100
            wins = cohort[cohort["total_net"] > 0]["total_net"].sum()
            losses = cohort[cohort["total_net"] < 0]["total_net"].sum()
            pf = wins / abs(losses) if losses != 0 else np.nan
            return tot, win_rate, pf
            
        g_net, g_win, g_pf = get_cohort_stats(good)
        b_net, b_win, b_pf = get_cohort_stats(bad)
        tot_net = df["total_net"].sum()
        
        wins = df[df["total_net"] > 0]["total_net"].sum()
        losses = df[df["total_net"] < 0]["total_net"].sum()
        tot_pf = wins / abs(losses) if losses != 0 else np.nan
        
        print(f"  Strategy {s:<2} | {len(df):>6} | "
              f"{g_net:>+10.2f}$ {g_win:>5.1f}% {g_pf:>6.2f} | "
              f"{b_net:>+10.2f}$ {b_win:>5.1f}% {b_pf:>6.2f} | "
              f"{tot_net:>+16.2f}$ | {tot_pf:>6.2f}")
              
    print("\n" + "-"*120)
    print("  Year-by-Year Performance Breakdown (Net PnL in $)")
    print("-"*120)
    print(f"  {'Strategy':<10} | {'2023':>12} | {'2024':>12} | {'2025':>12} | {'2026':>12} | {'Total OOS':>16}")
    print(f"  {'-'*10} | {'-'*12} | {'-'*12} | {'-'*12} | {'-'*12} | {'-'*16}")
    
    for s in STRATEGIES:
        df = sim_dfs[s]
        y_pnls = {}
        for y in (2023, 2024, 2025, 2026):
            y_pnls[y] = df[df["year"] == y]["total_net"].sum()
        tot_net = df["total_net"].sum()
        print(f"  Strategy {s:<2} | {y_pnls[2023]:>+12.2f}$ | {y_pnls[2024]:>+12.2f}$ | {y_pnls[2025]:>+12.2f}$ | {y_pnls[2026]:>+12.2f}$ | {tot_net:>+16.2f}$")
        
    print("="*120)
    print(f"Done in {time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()
