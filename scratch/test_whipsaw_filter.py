"""Test Whipsaw Reversal Filter on 2025 Rolling State 0

Evaluates if filtering out high-reversal setups (n_dir_changes_60s >= 13)
rescues the Expected Value of 2025.
"""
from __future__ import annotations
import os, sys, time
from pathlib import Path
import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))
os.chdir(project_root)

def main():
    # Load flips with excursions and rolling states
    # We can run the same setup but load the matched df directly from our previous script.
    # To make it fast, we will rebuild the 2025 OOS rolling model and test filters.
    
    from scratch.rolling_regime_study import load_1s, scan_exact_excursions, lookup_state_causal
    from sklearn.preprocessing import StandardScaler
    from sklearn.cluster import MiniBatchKMeans
    
    df_ex = pd.read_parquet("studies/regime_classification/results/flips_excursion_paths.parquet")
    df_ex_25 = df_ex[df_ex["year"] == 2025].copy()
    
    print("Loading NQ 2025 1s raw...")
    bars = load_1s(2025)
    ts_1s = bars.index.astype("int64").to_numpy()
    h_1s = bars["high"].to_numpy(np.float64)
    l_1s = bars["low"].to_numpy(np.float64)
    c_1s = bars["close"].to_numpy(np.float64)
    
    print("Scanning 1m excursions...")
    m1, ma1, t1 = scan_exact_excursions(
        df_ex_25["entry_ts"].to_numpy(np.int64),
        df_ex_25["entry_px"].to_numpy(np.float64),
        df_ex_25["entry_atr"].to_numpy(np.float64),
        df_ex_25["signal_direction"].to_numpy(np.int64),
        ts_1s, h_1s, l_1s, c_1s
    )
    df_ex_25["mfe_1m"] = m1
    df_ex_25["mae_1m"] = ma1
    df_ex_25["term_1m"] = t1
    
    # Load 1m features
    df_feat = pd.read_parquet("studies/regime_classification/results/features_nq_1m.parquet")
    from scratch.rolling_regime_study import FEATURE_COLS
    
    mask_feat = df_feat[FEATURE_COLS].notna().all(axis=1)
    df_feat_clean = df_feat[mask_feat].copy()
    if df_feat_clean.index.tz is None:
        df_feat_clean.index = df_feat_clean.index.tz_localize("UTC")
        
    # Get reference static centroid
    df_is = df_feat_clean[df_feat_clean["year"].isin((2020, 2021, 2022))]
    scaler_static = StandardScaler()
    X_is_scaled = scaler_static.fit_transform(df_is[FEATURE_COLS].values)
    static_km = MiniBatchKMeans(n_clusters=4, random_state=42, n_init=10, batch_size=4096)
    static_km.fit(X_is_scaled)
    range_idx = FEATURE_COLS.index("range_atr_300s")
    target_cluster_idx = np.argmax(static_km.cluster_centers_[:, range_idx])
    target_centroid = static_km.cluster_centers_[target_cluster_idx]
    
    # Quarterly rolling for 2025
    df_feat_clean["kmeans_rolling_q"] = -1
    df_oos = df_feat_clean[df_feat_clean["year"] == 2025].copy()
    df_oos["quarter_period"] = df_oos.index.to_period("Q")
    
    for q in sorted(df_oos["quarter_period"].unique()):
        q_start = q.start_time.tz_localize("UTC")
        lookback_start = q_start - pd.DateOffset(months=24)
        lookback_end = q_start - pd.Timedelta(seconds=1)
        
        df_train = df_feat_clean[(df_feat_clean.index >= lookback_start) & (df_feat_clean.index <= lookback_end)]
        df_test = df_oos[df_oos["quarter_period"] == q]
        
        scaler = StandardScaler()
        X_train = scaler.fit_transform(df_train[FEATURE_COLS].values)
        km = MiniBatchKMeans(n_clusters=4, random_state=42, n_init=10, batch_size=4096)
        km.fit(X_train)
        
        dists = [np.linalg.norm(c - target_centroid) for c in km.cluster_centers_]
        aligned_idx = np.argmin(dists)
        
        X_test = scaler.transform(df_test[FEATURE_COLS].values)
        test_labels = km.predict(X_test)
        df_feat_clean.loc[df_test.index, "kmeans_rolling_q"] = np.where(test_labels == aligned_idx, 0, -1)
        
    df_ex_25["kmeans_rolling_q"] = lookup_state_causal(
        df_ex_25["entry_ts"].to_numpy(np.int64),
        df_feat_clean.index.values.astype(np.int64),
        df_feat_clean["kmeans_rolling_q"].to_numpy(np.int64),
        60 * 1_000_000_000
    )
    
    # Load reversal feature at trigger time
    df_ex_25["n_dir_changes_60s"] = lookup_state_causal(
        df_ex_25["entry_ts"].to_numpy(np.int64),
        df_feat_clean.index.values.astype(np.int64),
        df_feat_clean["n_dir_changes_60s"].to_numpy(np.float64),
        60 * 1_000_000_000
    )
    df_ex_25["efficiency_300s"] = lookup_state_causal(
        df_ex_25["entry_ts"].to_numpy(np.int64),
        df_feat_clean.index.values.astype(np.int64),
        df_feat_clean["efficiency_300s"].to_numpy(np.float64),
        60 * 1_000_000_000
    )
    
    # Baseline 2025 OOS State 0 trades
    base_trig = df_ex_25[(df_ex_25["kmeans_rolling_q"] == 0) & (df_ex_25["entry_atr"] > 15.0)].copy()
    print(f"\nBaseline 2025 Rolling State 0 Trades: {len(base_trig)}")
    
    # Test filters on base_trig
    filters = [
        ("No Filter (Baseline)", lambda df: df),
        ("Low Micro-Reversals (n_dir_changes_60s < 13)", lambda df: df[df["n_dir_changes_60s"] < 13.0]),
        ("Clean Directional Path (efficiency_300s > 0.15)", lambda df: df[df["efficiency_300s"] > 0.15]),
        ("Combined (n_dir_changes_60s < 13 AND efficiency_300s > 0.15)", lambda df: df[(df["n_dir_changes_60s"] < 13.0) & (df["efficiency_300s"] > 0.15)])
    ]
    
    print("\n" + "="*80)
    print("  WHIPSAW FILTER SENSITIVITY SWEEP (2025 Rolling State 0)")
    print("="*80)
    print(f"  {'Filter setup':<55} {'Trades':>8} {'Win%':>8} {'Loss%':>8} {'Net PnL ($)':>13} {'PF':>6}")
    print("  " + "-"*95)
    
    for f_name, f_func in filters:
        sub = f_func(base_trig)
        if len(sub) == 0:
            print(f"  {f_name:<55} {0:>8}    -")
            continue
            
        mfe = sub["mfe_1m"].to_numpy()
        mae = sub["mae_1m"].to_numpy()
        term = sub["term_1m"].to_numpy()
        atrs = sub["entry_atr"].to_numpy()
        
        wins = (mfe >= 0.5) & (mae < 1.5)
        losses = (mae >= 1.5) | ((mfe >= 0.5) & (mae >= 1.5))
        flats = ~(wins | losses)
        
        pnl_atr = np.zeros(len(sub))
        pnl_atr[wins] = 0.5
        pnl_atr[losses] = -1.5
        pnl_atr[flats] = term[flats]
        
        pnl_usd = pnl_atr * atrs * 20.0 - 10.0
        pnl_usd = pnl_usd[~np.isnan(pnl_usd)]
        
        final_pnl = pnl_usd.sum() if len(pnl_usd) > 0 else 0.0
        
        pos_pnl = np.sum(pnl_usd[pnl_usd > 0])
        neg_pnl = -np.sum(pnl_usd[pnl_usd < 0])
        pf = pos_pnl / neg_pnl if neg_pnl > 0 else np.nan
        
        print(f"  {f_name:<55} {len(sub):>8,} {wins.mean():>7.1%} {losses.mean():>7.1%} {final_pnl:>+12.2f}$ {pf:>5.2f}")

if __name__ == "__main__":
    main()
