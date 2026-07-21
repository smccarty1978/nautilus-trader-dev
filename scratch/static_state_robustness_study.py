"""Static State 0 Robustness & Sensitivity Study (OOS 2023-2026)

Evaluates:
1. Year-by-year EV and trade frequency.
2. ATR-scaled PT/SL sensitivity sweeps.
3. Fixed-point bracket sweeps.
4. ATR bucket EV sweeps.
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
def scan_all_excursions(entry_ts_arr, entry_px_arr, entry_atr_arr, dir_arr,
                        ts_1s, high_1s, low_1s, close_1s):
    """Scan both ATR-scaled and absolute point excursions in a single pass."""
    N = len(entry_ts_arr)
    mfe_atr = np.full(N, np.nan)
    mae_atr = np.full(N, np.nan)
    term_atr = np.full(N, np.nan)
    
    mfe_pts = np.full(N, np.nan)
    mae_pts = np.full(N, np.nan)
    term_pts = np.full(N, np.nan)
    
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
                mfe_atr[i] = running_mfe / atr
                mae_atr[i] = running_mae / atr
                term_atr[i] = ((c - px_entry) * d) / atr
                
                mfe_pts[i] = running_mfe
                mae_pts[i] = running_mae
                term_pts[i] = (c - px_entry) * d
                recorded_1m = True
                
            j += 1
            
        if j > i_entry:
            last_idx = min(j - 1, len(ts_1s) - 1)
            c = close_1s[last_idx]
            if not recorded_1m:
                mfe_atr[i] = running_mfe / atr
                mae_atr[i] = running_mae / atr
                term_atr[i] = ((c - px_entry) * d) / atr
                
                mfe_pts[i] = running_mfe
                mae_pts[i] = running_mae
                term_pts[i] = (c - px_entry) * d
                
    return mfe_atr, mae_atr, term_atr, mfe_pts, mae_pts, term_pts


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
    
    # Re-scan for excursions (both ATR and absolute points)
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
        
        m_atr, ma_atr, t_atr, m_pts, ma_pts, t_pts = scan_all_excursions(
            year_cohort["entry_ts"].to_numpy(np.int64),
            year_cohort["entry_px"].to_numpy(np.float64),
            year_cohort["entry_atr"].to_numpy(np.float64),
            year_cohort["signal_direction"].to_numpy(np.int64),
            ts_1s, h_1s, l_1s, c_1s
        )
        
        year_cohort["mfe_1m_atr"] = m_atr
        year_cohort["mae_1m_atr"] = ma_atr
        year_cohort["term_1m_atr"] = t_atr
        year_cohort["mfe_1m_pts"] = m_pts
        year_cohort["mae_1m_pts"] = ma_pts
        year_cohort["term_1m_pts"] = t_pts
        
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
    
    # Match back to OOS triggers
    df_flips["kmeans_static_aligned"] = lookup_state_causal(
        df_flips["entry_ts"].to_numpy(np.int64),
        df_feat_clean.index.values.astype(np.int64),
        df_feat_clean["kmeans_static_aligned"].to_numpy(np.int64),
        60 * 1_000_000_000
    )
    
    df_flips_oos = df_flips[df_flips["year"].isin(OOS_YEARS)].copy().sort_values("entry_ts")
    df_static_oos_unfiltered = df_flips_oos[df_flips_oos["kmeans_static_aligned"] == 0].copy()
    df_static_oos = df_flips_oos[(df_flips_oos["kmeans_static_aligned"] == 0) & (df_flips_oos["entry_atr"] > 15.0)].copy()
    print(f"\nFiltered to {len(df_static_oos):,} OOS triggers in Static State 0 (ATR > 15)")
    
    # ── PART 1: ATR-SCALED BRACKET SWEEPS (Sensitivity Sweep) ──
    print("\n" + "="*80)
    print("  PART 1: ATR-SCALED BRACKET SENSITIVITY SWEEP (Static State 0 OOS)")
    print("="*80)
    print(f"  {'PT (ATR)':<10} {'SL (ATR)':<10} {'Trades':>8} {'Win%':>8} {'Loss%':>8} {'Flat%':>8} {'Net PnL ($)':>13} {'PF':>6}")
    print("  " + "-"*85)
    
    atr_targets = [0.4, 0.5, 0.6, 0.8, 1.0]
    atr_stops = [1.0, 1.2, 1.5, 1.8, 2.0]
    
    atr_results = []
    for tgt in atr_targets:
        for stp in atr_stops:
            mfe = df_static_oos["mfe_1m_atr"].to_numpy()
            mae = df_static_oos["mae_1m_atr"].to_numpy()
            term = df_static_oos["term_1m_atr"].to_numpy()
            atrs = df_static_oos["entry_atr"].to_numpy()
            
            wins = (mfe >= tgt) & (mae < stp)
            losses = (mae >= stp) | ((mfe >= tgt) & (mae >= stp))
            flats = ~(wins | losses)
            
            pnl_atr = np.zeros(len(df_static_oos))
            pnl_atr[wins] = tgt
            pnl_atr[losses] = -stp
            pnl_atr[flats] = term[flats]
            
            pnl_usd = pnl_atr * atrs * 20.0 - 10.0
            pnl_usd = pnl_usd[~np.isnan(pnl_usd)]
            final_pnl = pnl_usd.sum()
            
            pos_pnl = np.sum(pnl_usd[pnl_usd > 0])
            neg_pnl = -np.sum(pnl_usd[pnl_usd < 0])
            pf = pos_pnl / neg_pnl if neg_pnl > 0 else np.nan
            
            atr_results.append((tgt, stp, len(pnl_usd), wins.mean(), losses.mean(), flats.mean(), final_pnl, pf))
            
    # Sort by Net PnL descending
    atr_results.sort(key=lambda x: -x[6])
    for r in atr_results[:10]:
        print(f"  {r[0]:<10.1f} {r[1]:<10.1f} {r[2]:>8,} {r[3]:>7.1%} {r[4]:>7.1%} {r[5]:>7.1%} {r[6]:>+12.2f}$ {r[7]:>5.2f}")
        
    best_atr_setup = atr_results[0] # Best ATR setup for later bucket analyses
    
    # ── PART 2: FIXED-POINT BRACKET SWEEPS (Sensitivity Sweep) ──
    print("\n" + "="*80)
    print("  PART 2: FIXED-POINT BRACKET SENSITIVITY SWEEP (Static State 0 OOS)")
    print("="*80)
    print(f"  {'PT (pts)':<10} {'SL (pts)':<10} {'Trades':>8} {'Win%':>8} {'Loss%':>8} {'Flat%':>8} {'Net PnL ($)':>13} {'PF':>6}")
    print("  " + "-"*85)
    
    pt_targets = [5.0, 10.0, 15.0, 20.0, 25.0, 30.0]
    pt_stops = [5.0, 10.0, 15.0, 20.0, 25.0]
    
    pt_results = []
    for tgt in pt_targets:
        for stp in pt_stops:
            mfe = df_static_oos["mfe_1m_pts"].to_numpy()
            mae = df_static_oos["mae_1m_pts"].to_numpy()
            term = df_static_oos["term_1m_pts"].to_numpy()
            
            wins = (mfe >= tgt) & (mae < stp)
            losses = (mae >= stp) | ((mfe >= tgt) & (mae >= stp))
            flats = ~(wins | losses)
            
            pnl_pts = np.zeros(len(df_static_oos))
            pnl_pts[wins] = tgt
            pnl_pts[losses] = -stp
            pnl_pts[flats] = term[flats]
            
            pnl_usd = pnl_pts * 20.0 - 10.0
            pnl_usd = pnl_usd[~np.isnan(pnl_usd)]
            final_pnl = pnl_usd.sum()
            
            pos_pnl = np.sum(pnl_usd[pnl_usd > 0])
            neg_pnl = -np.sum(pnl_usd[pnl_usd < 0])
            pf = pos_pnl / neg_pnl if neg_pnl > 0 else np.nan
            
            pt_results.append((tgt, stp, len(pnl_usd), wins.mean(), losses.mean(), flats.mean(), final_pnl, pf))
            
    # Sort by Net PnL descending
    pt_results.sort(key=lambda x: -x[6])
    for r in pt_results[:10]:
        print(f"  {r[0]:<10.1f} {r[1]:<10.1f} {r[2]:>8,} {r[3]:>7.1%} {r[4]:>7.1%} {r[5]:>7.1%} {r[6]:>+12.2f}$ {r[7]:>5.2f}")
        
    best_fixed_setup = pt_results[0]
    
    # ── PART 3: YEAR-BY-YEAR ROBUSTNESS OF TOP SETUPS ──
    print("\n" + "="*80)
    print("  PART 3: YEAR-BY-YEAR PERFORMANCE AUDIT (OOS 2023-2026)")
    print("="*80)
    print(f"  Best ATR Setup:   PT={best_atr_setup[0]} ATR, SL={best_atr_setup[1]} ATR")
    print(f"  Best Fixed Setup: PT={best_fixed_setup[0]} pts, SL={best_fixed_setup[1]} pts")
    print(f"  {'Year':<10} {'Trades':>8} {'ATR Win%':>10} {'ATR Net PnL':>15} {'Fixed Win%':>12} {'Fixed Net PnL':>17}")
    print("  " + "-"*80)
    
    for y in OOS_YEARS:
        y_df = df_static_oos[df_static_oos["year"] == y]
        if len(y_df) == 0:
            print(f"  {y:<10} {0:>8}    -")
            continue
            
        # ATR Bracket run
        m_atr = y_df["mfe_1m_atr"].to_numpy()
        ma_atr = y_df["mae_1m_atr"].to_numpy()
        t_atr = y_df["term_1m_atr"].to_numpy()
        atrs_y = y_df["entry_atr"].to_numpy()
        wins_a = (m_atr >= best_atr_setup[0]) & (ma_atr < best_atr_setup[1])
        losses_a = (ma_atr >= best_atr_setup[1]) | ((m_atr >= best_atr_setup[0]) & (ma_atr >= best_atr_setup[1]))
        flats_a = ~(wins_a | losses_a)
        p_atr_y = np.zeros(len(y_df))
        p_atr_y[wins_a] = best_atr_setup[0]
        p_atr_y[losses_a] = -best_atr_setup[1]
        p_atr_y[flats_a] = t_atr[flats_a]
        pnl_usd_a = p_atr_y * atrs_y * 20.0 - 10.0
        pnl_usd_a = pnl_usd_a[~np.isnan(pnl_usd_a)]
        final_pnl_a = pnl_usd_a.sum()
        
        # Fixed Bracket run
        m_pts = y_df["mfe_1m_pts"].to_numpy()
        ma_pts = y_df["mae_1m_pts"].to_numpy()
        t_pts = y_df["term_1m_pts"].to_numpy()
        wins_f = (m_pts >= best_fixed_setup[0]) & (ma_pts < best_fixed_setup[1])
        losses_f = (ma_pts >= best_fixed_setup[1]) | ((m_pts >= best_fixed_setup[0]) & (ma_pts >= best_fixed_setup[1]))
        flats_f = ~(wins_f | losses_f)
        p_pts_y = np.zeros(len(y_df))
        p_pts_y[wins_f] = best_fixed_setup[0]
        p_pts_y[losses_f] = -best_fixed_setup[1]
        p_pts_y[flats_f] = t_pts[flats_f]
        pnl_usd_f = p_pts_y * 20.0 - 10.0
        pnl_usd_f = pnl_usd_f[~np.isnan(pnl_usd_f)]
        final_pnl_f = pnl_usd_f.sum()
        
        print(f"  {y:<10} {len(y_df):>8,} {wins_a.mean():>9.1%} {final_pnl_a:>+14.2f}$ {wins_f.mean():>11.1%} {final_pnl_f:>+16.2f}$")

    # ── PART 4: ATR BUCKET SENSITIVITY FOR THE BEST SETUP ──
    print("\n" + "="*80)
    print("  PART 4: ATR BUCKET NET EV SENSITIVITY (Best ATR Setup)")
    print("="*80)
    
    def assign_bucket(atr):
        if atr <= 10.0: return "Low Vol (<=10)"
        if atr <= 15.0: return "Mid Vol (10-15)"
        if atr <= 20.0: return "High Vol (15-20)"
        return "Extreme Vol (>20)"
        
    df_static_oos_unfiltered["vol_bucket"] = df_static_oos_unfiltered["entry_atr"].apply(assign_bucket)
    buckets = ["Low Vol (<=10)", "Mid Vol (10-15)", "High Vol (15-20)", "Extreme Vol (>20)"]
    
    print(f"  {'ATR Volatility Bucket':<25} {'Trades':>8} {'Win%':>8} {'Loss%':>8} {'Flat%':>8} {'Net PnL ($)':>13} {'PF':>6}")
    print("  " + "-"*80)
    for b in buckets:
        sub = df_static_oos_unfiltered[df_static_oos_unfiltered["vol_bucket"] == b].copy()
        if len(sub) == 0:
            print(f"  {b:<25} {0:>8}    -")
            continue
            
        mfe = sub["mfe_1m_atr"].to_numpy()
        mae = sub["mae_1m_atr"].to_numpy()
        term = sub["term_1m_atr"].to_numpy()
        atrs = sub["entry_atr"].to_numpy()
        
        wins = (mfe >= best_atr_setup[0]) & (mae < best_atr_setup[1])
        losses = (mae >= best_atr_setup[1]) | ((mfe >= best_atr_setup[0]) & (mae >= best_atr_setup[1]))
        flats = ~(wins | losses)
        
        p_atr = np.zeros(len(sub))
        p_atr[wins] = best_atr_setup[0]
        p_atr[losses] = -best_atr_setup[1]
        p_atr[flats] = term[flats]
        
        pnl_usd = p_atr * atrs * 20.0 - 10.0
        pnl_usd = pnl_usd[~np.isnan(pnl_usd)]
        final_pnl = pnl_usd.sum()
        
        pos_pnl = np.sum(pnl_usd[pnl_usd > 0])
        neg_pnl = -np.sum(pnl_usd[pnl_usd < 0])
        pf = pos_pnl / neg_pnl if neg_pnl > 0 else np.nan
        
        print(f"  {b:<25} {len(sub):>8,} {wins.mean():>7.1%} {losses.mean():>7.1%} {flats.mean():>7.1%} {final_pnl:>+12.2f}$ {pf:>5.2f}")
        
    print(f"\n[done] {(time.time()-t_start)/60:.2f} min")


if __name__ == "__main__":
    main()
