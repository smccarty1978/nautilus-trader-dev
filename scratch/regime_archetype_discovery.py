import pandas as pd
import numpy as np
import os
from pathlib import Path
from sklearn.preprocessing import StandardScaler
from sklearn.cluster import KMeans

PROJECT_ROOT = Path(r"c:\Users\Scott McCarty\Projects\Nautilus Trader")
OUT_DIR = PROJECT_ROOT / "studies/regime_state_transition_atlas/results"

def main():
    print("Loading state_rows.parquet...")
    # Load state rows, which contains bar-by-bar features for every regime
    df = pd.read_parquet(OUT_DIR / "state_rows.parquet")
    
    # We'll use 2021-2024 for training the archetypes, or just cluster everything
    print("Aggregating regime features...")
    
    # Sort to ensure first/last operations are chronologically correct
    df = df.sort_values(['regime_id', 'bar_index_in_regime'])
    
    # Aggregate into regime-level vectors
    agg_funcs = {
        'bar_index_in_regime': 'max',                   # length
        'mfe_so_far_atr': 'max',                        # total MFE
        'mae_so_far_atr': 'max',                        # total MAE
        '5s_flip_count_since_1m_start': 'max',          # num 5s flips (pullbacks)
        'pullback_from_peak_atr': 'max',                # max pullback
        'volume_percentile_20': 'mean',                 # mean volume profile
        'distance_to_ema9_atr': 'mean',                 # mean ema distance
        'ema9_slope_atr': ['first', 'last']             # slope profile
    }
    
    regimes = df.groupby('regime_id').agg(agg_funcs)
    
    # Flatten multi-level columns
    regimes.columns = [
        'length_bars',
        'total_mfe_atr',
        'total_mae_atr',
        'num_5s_flips',
        'max_pullback_atr',
        'mean_volume_pct',
        'mean_ema_dist_atr',
        'start_slope_atr',
        'end_slope_atr'
    ]
    
    # Drop any regimes with NaNs (if any)
    regimes = regimes.dropna()
    
    # Filter out trivial regimes (e.g., length < 3 bars) if desired, but let's keep all
    print(f"Extracted {len(regimes):,} regimes.")
    
    print("Scaling features...")
    scaler = StandardScaler()
    X = scaler.fit_transform(regimes)
    
    n_clusters = 12
    print(f"Running K-Means clustering (k={n_clusters})...")
    kmeans = KMeans(n_clusters=n_clusters, random_state=42, n_init=10)
    regimes['archetype'] = kmeans.fit_predict(X)
    
    print("Generating Archetype Summary...")
    lines = ["# Regime Archetypes Summary\n"]
    lines.append(f"Clustered {len(regimes):,} regimes into {n_clusters} distinct archetypes using K-Means.\n")
    
    # Analyze each archetype
    for i in range(n_clusters):
        cluster_data = regimes[regimes['archetype'] == i]
        pct = len(cluster_data) / len(regimes) * 100
        
        lines.append(f"### Archetype {i}")
        lines.append(f"* **Size:** {len(cluster_data):,} regimes ({pct:.1f}%)")
        lines.append(f"* **Avg Length:** {cluster_data['length_bars'].mean():.1f} bars")
        lines.append(f"* **Avg MFE:** {cluster_data['total_mfe_atr'].mean():.2f} ATR")
        lines.append(f"* **Avg MAE:** {cluster_data['total_mae_atr'].mean():.2f} ATR")
        lines.append(f"* **Avg 5s Flips:** {cluster_data['num_5s_flips'].mean():.1f}")
        lines.append(f"* **Max Pullback:** {cluster_data['max_pullback_atr'].mean():.2f} ATR")
        lines.append(f"* **Mean EMA Dist:** {cluster_data['mean_ema_dist_atr'].mean():.2f} ATR")
        lines.append(f"* **Start Slope:** {cluster_data['start_slope_atr'].mean():.3f} ATR")
        lines.append(f"* **End Slope:** {cluster_data['end_slope_atr'].mean():.3f} ATR\n")
        
        # Simple heuristic name
        mfe = cluster_data['total_mfe_atr'].mean()
        mae = cluster_data['total_mae_atr'].mean()
        length = cluster_data['length_bars'].mean()
        flips = cluster_data['num_5s_flips'].mean()
        
        if mfe > 3.0 and flips < 2:
            name = "Explosive Trend"
        elif mfe > 2.0 and flips >= 2:
            name = "Grinding Trend"
        elif mfe < 1.0 and length > 10:
            name = "Chop/Consolidation"
        elif mae > 1.5 and mfe < 1.0:
            name = "V-Reversal / Failed Regime"
        else:
            name = "Standard Trend / Mixed"
            
        lines.append(f"**Structural Profile:** {name}")
        lines.append("---\n")
        
    out_path = OUT_DIR / "archetypes_summary.md"
    with open(out_path, 'w', encoding='utf-8') as f:
        f.write("\n".join(lines))
        
    print(f"Wrote {out_path}")

if __name__ == "__main__":
    main()
