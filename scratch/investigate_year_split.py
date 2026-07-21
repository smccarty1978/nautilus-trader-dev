"""Investigate Year Split (2024/2025 vs 2023/2026) for Static State 0 + ATR > 15

Compares:
- Excursion paths (MFE / MAE) and times to MFE/MAE
- State run lengths and session position
- Directional bias (Long vs Short)
- Feature signatures (ATR, RV, Efficiency, Chop, VWAP distance)
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
    print(f"Loaded {len(df_ex):,} flips.")
    
    # Re-scan for excursions and times
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
    
    # 2. Load 1m raw features and static states
    df_feat = pd.read_parquet("studies/regime_classification/results/features_nq_1m.parquet")
    states_1m = pd.read_parquet("studies/regime_classification/results/states_nq_1m.parquet")
    df_feat["kmeans_static"] = states_1m["kmeans_4"]
    
    mask_feat = df_feat[FEATURE_COLS].notna().all(axis=1)
    df_feat_clean = df_feat[mask_feat].copy()
    if df_feat_clean.index.tz is None:
        df_feat_clean.index = df_feat_clean.index.tz_localize("UTC")
        
    # Re-align Static Target State 0 (highest range_atr_300s cluster)
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
    
    # Match back to triggers
    df_flips["kmeans_static_aligned"] = lookup_state_causal(
        df_flips["entry_ts"].to_numpy(np.int64),
        df_feat_clean.index.values.astype(np.int64),
        df_feat_clean["kmeans_static_aligned"].to_numpy(np.int64),
        60 * 1_000_000_000,
        is_int=True
    )
    
    # 3. Add feature lookups at trade entry
    for col in ["rv_300s", "efficiency_300s", "chop_ratio_300s", "vwap_z_abs", "session_pos"]:
        df_flips[col] = lookup_state_causal(
            df_flips["entry_ts"].to_numpy(np.int64),
            df_feat_clean.index.values.astype(np.int64),
            df_feat_clean[col].to_numpy(np.float64),
            60 * 1_000_000_000,
            is_int=False
        )
        
    # Calculate state run lengths (regime duration)
    def calc_run_lengths(state_series):
        runs = []
        current_run = 0
        for val in state_series:
            if val == 0:
                current_run += 1
            else:
                if current_run > 0:
                    runs.append(current_run * 60.0) # convert to seconds
                    current_run = 0
        if current_run > 0:
            runs.append(current_run * 60.0)
        return np.array(runs)
        
    runs_24_25 = calc_run_lengths(df_feat_clean[df_feat_clean["year"].isin((2024, 2025))]["kmeans_static_aligned"].values)
    runs_23_26 = calc_run_lengths(df_feat_clean[df_feat_clean["year"].isin((2023, 2026))]["kmeans_static_aligned"].values)
    
    # Filter to State 0 + ATR > 15 population
    pop = df_flips[(df_flips["year"].isin((2023, 2024, 2025, 2026))) & (df_flips["kmeans_static_aligned"] == 0) & (df_flips["entry_atr"] > 15.0)].copy()
    
    # Split into winning years (2024/2025) vs bad years (2023/2026)
    win_pop = pop[pop["year"].isin((2024, 2025))].copy()
    bad_pop = pop[pop["year"].isin((2023, 2026))].copy()
    
    print("\n" + "="*80)
    print("  YEAR-SPLIT POPULATION COMPARISON: STATIC STATE 0 + ATR > 15")
    print("="*80)
    print(f"  {'Metric':<28} {'Winning Years (24/25)':>23} {'Bad Years (23/26)':>23}")
    print("  " + "-"*80)
    print(f"  {'Trade Count':<28} {len(win_pop):>23,} {len(bad_pop):>23,}")
    
    # Excursion paths
    print(f"  {'Mean MFE (1m)':<28} {win_pop['mfe_1m_atr'].mean():>22.3f}x {bad_pop['mfe_1m_atr'].mean():>22.3f}x")
    print(f"  {'Mean MAE (1m)':<28} {win_pop['mae_1m_atr'].mean():>22.3f}x {bad_pop['mae_1m_atr'].mean():>22.3f}x")
    print(f"  {'Mean Terminal PnL (ATR)':<28} {win_pop['term_1m_atr'].mean():>+22.3f}x {bad_pop['term_1m_atr'].mean():>+22.3f}x")
    
    # Bracket times
    print(f"  {'Time to MFE (s)':<28} {win_pop['time_to_mfe_s'].mean():>22.1f}s {bad_pop['time_to_mfe_s'].mean():>22.1f}s")
    print(f"  {'Time to MAE (s)':<28} {win_pop['time_to_mae_s'].mean():>22.1f}s {bad_pop['time_to_mae_s'].mean():>22.1f}s")
    
    # Regime durations
    print(f"  {'Regime Duration (s)':<28} {runs_24_25.mean():>22.1f}s {runs_23_26.mean():>22.1f}s")
    
    # Session dynamics & Direction
    win_long = (win_pop["signal_direction"] == 1).mean() * 100
    bad_long = (bad_pop["signal_direction"] == 1).mean() * 100
    print(f"  {'Long Trades %':<28} {win_long:>22.1f}% {bad_long:>22.1f}%")
    print(f"  {'Mean Session Position':<28} {win_pop['session_pos'].mean():>22.3f} {bad_pop['session_pos'].mean():>22.3f}")
    
    # Features
    print(f"  {'Mean entry ATR':<28} {win_pop['entry_atr'].mean():>22.1f} {bad_pop['entry_atr'].mean():>22.1f}")
    print(f"  {'Mean entry RV (300s)':<28} {win_pop['rv_300s'].mean():>22.5f} {bad_pop['rv_300s'].mean():>22.5f}")
    print(f"  {'Mean entry Efficiency':<28} {win_pop['efficiency_300s'].mean():>22.4f} {bad_pop['efficiency_300s'].mean():>22.4f}")
    print(f"  {'Mean entry Chop':<28} {win_pop['chop_ratio_300s'].mean():>22.2f} {bad_pop['chop_ratio_300s'].mean():>22.2f}")
    print(f"  {'Mean entry VWAP z-abs':<28} {win_pop['vwap_z_abs'].mean():>22.3f} {bad_pop['vwap_z_abs'].mean():>22.3f}")
    
    # ── PT=0.5 ATR / SL=1.5 ATR Bracket outcomes ──
    def get_outcomes(df):
        mfe = df["mfe_1m_atr"].to_numpy()
        mae = df["mae_1m_atr"].to_numpy()
        term = df["term_1m_atr"].to_numpy()
        wins = (mfe >= 0.5) & (mae < 1.5)
        losses = (mae >= 1.5) | ((mfe >= 0.5) & (mae >= 1.5))
        flats = ~(wins | losses)
        
        # Calculate gross dollar values
        atrs = df["entry_atr"].to_numpy()
        p_atr = np.zeros(len(df))
        p_atr[wins] = 0.5
        p_atr[losses] = -1.5
        p_atr[flats] = term[flats]
        
        pnl_gross = p_atr * atrs * 20.0
        commission = np.full(len(df), -10.0)
        pnl_net = pnl_gross + commission
        
        return wins.mean()*100, losses.mean()*100, flats.mean()*100, pnl_gross.mean(), pnl_net.mean()
        
    w_w, l_w, f_w, gr_w, nt_w = get_outcomes(win_pop)
    w_b, l_b, f_b, gr_b, nt_b = get_outcomes(bad_pop)
    
    print("\n" + "="*80)
    print("  SIMULATED OUTCOMES SWEEP: 2024/2025 vs 2023/2026 (0.5 PT / 1.5 SL / 1m exit)")
    print("="*80)
    print(f"  {'Metric':<28} {'Winning Years (24/25)':>23} {'Bad Years (23/26)':>23}")
    print("  " + "-"*80)
    print(f"  {'Bracket Win % (PT hit)':<28} {w_w:>22.1f}% {w_b:>22.1f}%")
    print(f"  {'Bracket Loss % (SL hit)':<28} {l_w:>22.1f}% {l_b:>22.1f}%")
    print(f"  {'Bracket Flat % (Time Exit)':<28} {f_w:>22.1f}% {f_b:>22.1f}%")
    print(f"  {'Gross EV per Trade ($)':<28} {gr_w:>+22.2f}$ {gr_b:>+22.2f}$")
    print(f"  {'Net EV per Trade ($)':<28} {nt_w:>+22.2f}$ {nt_b:>+22.2f}$")
    
    print(f"\n[done] {(time.time()-t0)/60:.2f} min")


if __name__ == "__main__":
    main()
