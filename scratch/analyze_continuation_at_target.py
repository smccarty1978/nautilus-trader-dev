"""Analyze Continuation Predictability at the +0.50 ATR Target Touch Point

For the Static State 0 + ATR > 15 out-of-sample population (2023-2026):
1. Trace the 1s price path of each trade.
2. Filter to trades that successfully touch the +0.50 ATR target.
3. Classify each trade's future outcome from that touch point:
   - "continue": MFE reaches >= 1.00 ATR or close is >= 0.75 ATR.
   - "revert": retraces to BE (entry price) or SL (-1.50 ATR) first.
4. Extract causal features at the exact minute the trade touched +0.50 ATR:
   - distance from VWAP (vwap_z_abs)
   - slope (vwap_slope_5m_atr)
   - realized variance (rv_30s, rv_300s)
   - path efficiency (efficiency_300s)
   - chop ratio (chop_ratio_300s)
   - time of day (session_pos)
   - state persistence (consecutive bars in target State 0)
5. Group by:
   - Good Years (2024/2025) vs. Bad Years (2023/2026)
   - Persistent Continuers vs. Mean Reverters
6. Calculate mean, std, and t-statistic/z-score differences to find observable predictors.
"""
from __future__ import annotations
import os, sys, time
from pathlib import Path
import numpy as np
import pandas as pd
from scipy import stats
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
    
    # Load static states and features
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
    
    # Convert features to dictionary for quick causal lookup
    feature_lookup_ts = df_feat_clean.index.values.astype(np.int64)
    feature_dicts = {}
    features_to_extract = ["vwap_z_abs", "vwap_slope_5m_atr", "rv_30s", "rv_300s", "efficiency_300s", "chop_ratio_300s", "session_pos"]
    for col in features_to_extract:
        feature_dicts[col] = dict(zip(feature_lookup_ts, df_feat_clean[col].values))
        
    state_lookup = dict(zip(feature_lookup_ts, df_feat_clean["kmeans_static_aligned"].values))

    # Trace each trade to find +0.50 ATR touch point and future outcome
    trades_analyzed = []
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
        
        pt_px = entry_px + d * 0.50 * atr
        sl_px = entry_px - d * 1.50 * atr
        pt_1atr = entry_px + d * 1.00 * atr
        revert_px = entry_px  # Break-even stop
        
        touch_idx = -1
        for j in range(idx_start, idx_end + 1):
            h, l = h_1s[j], l_1s[j]
            if (d == 1 and h >= pt_px) or (d == -1 and l <= pt_px):
                touch_idx = j
                break
                
        # If it never touches +0.50 ATR, exclude
        if touch_idx == -1:
            continue
            
        # Classify future outcome from touch point
        future_outcome = "unknown"
        for j in range(touch_idx + 1, idx_end + 1):
            h, l = h_1s[j], l_1s[j]
            # Hits continuer target (1.00 ATR) first
            if (d == 1 and h >= pt_1atr) or (d == -1 and l <= pt_1atr):
                future_outcome = "continue"
                break
            # Hits reverter stop (BE or SL) first
            if (d == 1 and l <= revert_px) or (d == -1 and h >= revert_px):
                future_outcome = "revert"
                break
                
        if future_outcome == "unknown":
            # Time exit or regime close fallback
            terminal_px = c_1s[idx_end]
            terminal_atr_change = (terminal_px - entry_px) * d / atr
            if terminal_atr_change >= 0.75:
                future_outcome = "continue"
            else:
                future_outcome = "revert"
                
        # Extract features at the touch point causally
        touch_ts = ts_1s[touch_idx]
        # Open timestamp of the latest closed 1m bar
        t_closed_open = (touch_ts // 60_000_000_000) * 60_000_000_000 - 60_000_000_000
        
        feat_vals = {}
        for col in features_to_extract:
            feat_vals[col] = feature_dicts[col].get(t_closed_open, np.nan)
            
        # Calculate State 0 persistence
        persistence = 0
        curr_ts = t_closed_open
        while state_lookup.get(curr_ts, -1) == 0:
            persistence += 1
            curr_ts -= 60_000_000_000
            if persistence > 60: # safety break
                break
        feat_vals["persistence"] = persistence
        
        trades_analyzed.append({
            "year": y,
            "signal_direction": d,
            "entry_atr": atr,
            "future_outcome": future_outcome,
            **feat_vals
        })
        
    df_ana = pd.DataFrame(trades_analyzed)
    print(f"Analyzed {len(df_ana)} trades that successfully reached the +0.50 ATR target.")
    
    # ── SLICE 1: Good Years vs. Bad Years ──
    good_mask = df_ana["year"].isin((2024, 2025))
    bad_mask = df_ana["year"].isin((2023, 2026))
    
    df_good = df_ana[good_mask]
    df_bad = df_ana[bad_mask]
    
    print("\n" + "="*120)
    print("  SLICE 1 ANALYSIS: GOOD YEARS (2024/2025) VS. BAD YEARS (2023/2026) AT TARGET TOUCH POINT")
    print("="*120)
    print(f"  {'Feature Name':<25} | {'Good Years (n={}):^18'.format(len(df_good))} | {'Bad Years (n={}):^18'.format(len(df_bad))} | {'z-Score Diff':>12} | {'t-Stat / p-Val':>20}")
    print("  " + "-"*116)
    
    all_features = features_to_extract + ["persistence"]
    for feat in all_features:
        g_vals = df_good[feat].dropna().values
        b_vals = df_bad[feat].dropna().values
        
        g_mean, g_std = np.mean(g_vals), np.std(g_vals, ddof=1)
        b_mean, b_std = np.mean(b_vals), np.std(b_vals, ddof=1)
        
        t_stat, p_val = stats.ttest_ind(g_vals, b_vals, equal_var=False)
        
        # Standardized effect size (Cohen's d style or z-score)
        pooled_std = np.sqrt(((len(g_vals)-1)*g_std**2 + (len(b_vals)-1)*b_std**2)/(len(g_vals)+len(b_vals)-2))
        z_diff = (g_mean - b_mean) / pooled_std if pooled_std > 0 else 0.0
        
        print(f"  {feat:<25} | {g_mean:>8.4f} (±{g_std:>6.4f}) | {b_mean:>8.4f} (±{b_std:>6.4f}) | {z_diff:>+11.2f}σ | {t_stat:>+8.3f} ({p_val:>5.3f})")

    # ── SLICE 2: Persistent Continuers vs. Mean Reverters ──
    cont_mask = df_ana["future_outcome"] == "continue"
    rev_mask = df_ana["future_outcome"] == "revert"
    
    df_cont = df_ana[cont_mask]
    df_rev = df_ana[rev_mask]
    
    print("\n" + "="*120)
    print("  SLICE 2 ANALYSIS: PERSISTENT CONTINUERS (MFE>=1.0 ATR) VS. MEAN REVERTERS (BE/SL HIT) AT TOUCH POINT")
    print("="*120)
    print(f"  {'Feature Name':<25} | {'Continuers (n={}):^18'.format(len(df_cont))} | {'Reverters (n={}):^18'.format(len(df_rev))} | {'z-Score Diff':>12} | {'t-Stat / p-Val':>20}")
    print("  " + "-"*116)
    
    for feat in all_features:
        c_vals = df_cont[feat].dropna().values
        r_vals = df_rev[feat].dropna().values
        
        c_mean, c_std = np.mean(c_vals), np.std(c_vals, ddof=1)
        r_mean, r_std = np.mean(r_vals), np.std(r_vals, ddof=1)
        
        t_stat, p_val = stats.ttest_ind(c_vals, r_vals, equal_var=False)
        
        # Effect size
        pooled_std = np.sqrt(((len(c_vals)-1)*c_std**2 + (len(r_vals)-1)*r_std**2)/(len(c_vals)+len(r_vals)-2))
        z_diff = (c_mean - r_mean) / pooled_std if pooled_std > 0 else 0.0
        
        print(f"  {feat:<25} | {c_mean:>8.4f} (±{c_std:>6.4f}) | {r_mean:>8.4f} (±{r_std:>6.4f}) | {z_diff:>+11.2f}σ | {t_stat:>+8.3f} ({p_val:>5.3f})")

    # ── SLICE 3: Combined Predictive Matrix ──
    print("\n" + "="*120)
    print("  SLICE 3: COHORT OVERLAP & PREDICTIVE ACCURACY BY persistence & vwap_z_abs THRESHOLDS")
    print("="*120)
    # We will test two thresholds:
    # 1. State Persistence <= 2 (young trend bursts) vs > 2 (mature/tired states)
    # 2. distance from VWAP (vwap_z_abs) <= 1.0 (mean reversion safety zone) vs > 1.0 (exhaustion zone)
    
    def test_filter(label, mask):
        filtered = df_ana[mask]
        n_filt = len(filtered)
        if n_filt == 0:
            print(f"  {label:<55} | Trades: 0 | Win Rate: N/A | Continuer %: N/A")
            return
        c_pct = (filtered["future_outcome"] == "continue").mean() * 100
        # If we traded Strategy A on this filtered cohort:
        # Win is +0.50 ATR, Loss is -1.50 ATR.
        # But wait, in Strategy A, let's see how many actually continued or reverted.
        # Continuer gives +0.5 ATR, reverter also hit PT 0.5 ATR!
        # Ah! In Strategy A, both contracts exited at PT +0.50 ATR anyway!
        # So for a filtered cohort, if we held the RUNNER (Strategy B), the Continuer % is exactly the runner win rate!
        print(f"  {label:<55} | Trades: {n_filt:>3} | Continuer %: {c_pct:>5.1f}%")
        
    test_filter("Unfiltered Base Cohort at +0.50 ATR Touch", np.ones(len(df_ana), dtype=bool))
    test_filter("Young Trend Burst (State Persistence <= 2)", df_ana["persistence"] <= 2)
    test_filter("Mature/Exhausted Trend (State Persistence > 2)", df_ana["persistence"] > 2)
    test_filter("Near VWAP Zone (vwap_z_abs <= 1.0)", df_ana["vwap_z_abs"] <= 1.0)
    test_filter("Extreme VWAP Distance (vwap_z_abs > 1.0)", df_ana["vwap_z_abs"] > 1.0)
    test_filter("The Sweet Spot: Young Burst AND Near VWAP (Persistence <= 2 & vwap_z_abs <= 1.0)", (df_ana["persistence"] <= 2) & (df_ana["vwap_z_abs"] <= 1.0))
    test_filter("The Exhaustion Zone: Mature Burst OR Extreme VWAP", (df_ana["persistence"] > 2) | (df_ana["vwap_z_abs"] > 1.0))
    print("="*120)
    print(f"Done in {time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()
