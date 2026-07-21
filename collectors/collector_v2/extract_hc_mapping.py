"""Extract Bar-4 hC mapping for NautilusTrader event-driven backtests.
Runs the exact Study 7 walk-forward KNN algorithm at k=4 (Bar 4 close)
and maps each regime's start timestamp (nanoseconds) to its hC score.
"""

from __future__ import annotations
import sys
from pathlib import Path
import numpy as np
import pandas as pd
from sklearn.neighbors import NearestNeighbors

# Setup paths
PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "studies" / "regime_dna_knn"))

import early_health_filter as E
import progressive_separability as P
import bar4_knn_path_atlas as A

OUT = PROJECT_ROOT / "studies" / "regime_dna_knn" / "results"
KNN_K = 500
IS_REF_CAP = 40000
RNG = np.random.default_rng(0)

def main():
    print("Loading early health capsule data...")
    cap = pd.read_parquet(OUT / "early_health_capsule.parquet")
    df = E.compute_labels_features(cap).reset_index(drop=True)
    M = P.build(df)
    
    print("Building states DataFrame...")
    # S contains state vectors at each bar k for each regime
    A.BARS = [4]  # Optimize: we only need Bar 4 close features
    S = A.build_states(df, M)
    
    # We only care about k=4 (Bar 4 close)
    S = S[S.k == 4].copy().reset_index(drop=True)
    
    print(f"Total regimes at k=4: {len(S)}")
    
    # Run walk-forward KNN for years 2022-2026
    pNH3 = np.full(len(S), np.nan)
    pFL3 = np.full(len(S), np.nan)
    
    for year in [2022, 2023, 2024, 2025, 2026]:
        db = S[S.year < year] if year < 2025 else S[S.year < 2025]
        q = S[S.year == year]
        if len(q) == 0 or len(db) < 200:
            print(f"Skipping year {year} (insufficient data)")
            continue
            
        print(f"Running walk-forward KNN for year {year} (OOS={len(q)}, IS={len(db)})...")
        
        # Subsample IS if too large
        if len(db) > IS_REF_CAP:
            db_sub = db.iloc[RNG.choice(len(db), IS_REF_CAP, replace=False)]
        else:
            db_sub = db
            
        Xis = db_sub[A.FEATS].values.astype(np.float32)
        Xoo = q[A.FEATS].values.astype(np.float32)
        
        # Standardize features
        mu = Xis.mean(0)
        sd = Xis.std(0)
        sd[sd == 0] = 1.0
        
        # Fit KNN
        nn = NearestNeighbors(n_neighbors=min(KNN_K, len(db_sub)), n_jobs=-1)
        nn.fit((Xis - mu) / sd)
        
        # Query nearest neighbors
        _, idx = nn.kneighbors((Xoo - mu) / sd)
        
        # Get target outcomes
        oi = q.index.values
        pNH3[oi] = db_sub.newhigh3.values[idx].mean(1)
        pFL3[oi] = db_sub.flip3.values[idx].mean(1)
        
    S["pNH3"] = pNH3
    S["pFL3"] = pFL3
    S["hC"] = S.pNH3 - S.pFL3
    
    # Filter for valid hC predictions (OOS 2022-2026)
    S_valid = S[S.hC.notna()].copy()
    print(f"Valid predictions: {len(S_valid)}")
    
    # Merge with original df to get regime_start_ts
    merged = df.merge(S_valid, left_on="regime_id", right_on="rid")
    
    # Save the mapping
    mapping_df = merged[["regime_start_ts", "regime_id", "hC", "pNH3", "pFL3"]].copy()
    mapping_df.rename(columns={"regime_id": "rid"}, inplace=True)
    
    out_dir = PROJECT_ROOT / "collectors" / "collector_v2" / "results"
    out_dir.mkdir(parents=True, exist_ok=True)
    
    out_path = out_dir / "hc_bar4_mapping.parquet"
    mapping_df.to_parquet(out_path, index=False)
    print(f"Saved hC mapping to {out_path} ({len(mapping_df)} records)")

if __name__ == "__main__":
    main()
