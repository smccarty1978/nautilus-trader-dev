import json
from pathlib import Path
import joblib
import numpy as np
import pandas as pd


def check_candidate_directions():
    print("=== Phase 2: Candidate Population Prevailing-Regime Audit ===")
    
    # Short candidates
    s24 = pd.read_parquet("studies/short_rth_enriched_volume_level_retrain/_work/prepared_2024.parquet")
    s25 = pd.read_parquet("studies/short_rth_enriched_volume_level_retrain/_work/prepared_2025.parquet")
    s_df = pd.concat([s24, s25], ignore_index=True)
    
    print(f"Short candidate total rows: {len(s_df)}")
    print("Short candidate columns related to direction/regime:")
    dir_cols_s = [c for c in s_df.columns if "dir" in c or "regime" in c or "side" in c or "trend" in c]
    print(dir_cols_s)
    
    if "regime_dir" in s_df.columns:
        print("Short regime_dir value_counts:", s_df["regime_dir"].value_counts().to_dict())
    if "direction" in s_df.columns:
        print("Short direction value_counts:", s_df["direction"].value_counts().to_dict())
        
    # Long candidates
    l24 = pd.read_parquet("studies/long_rth_mirrored_surface_top100_training/_work/prepared_long_2024.parquet")
    l25 = pd.read_parquet("studies/long_rth_mirrored_surface_top100_training/_work/prepared_long_2025.parquet")
    l_df = pd.concat([l24, l25], ignore_index=True)
    
    print(f"Long candidate total rows: {len(l_df)}")
    print("Long candidate columns related to direction/regime:")
    dir_cols_l = [c for c in l_df.columns if "dir" in c or "regime" in c or "side" in c or "trend" in c]
    print(dir_cols_l)
    
    if "regime_dir" in l_df.columns:
        print("Long regime_dir value_counts:", l_df["regime_dir"].value_counts().to_dict())
    if "direction" in l_df.columns:
        print("Long direction value_counts:", l_df["direction"].value_counts().to_dict())
    print("-" * 50)


def run_first_divergence_trace():
    print("=== Phase 3: First-Divergence Trace (20 Short Signals) ===")
    
    # Load short candidates & score
    s24 = pd.read_parquet("studies/short_rth_enriched_volume_level_retrain/_work/prepared_2024.parquet")
    s25 = pd.read_parquet("studies/short_rth_enriched_volume_level_retrain/_work/prepared_2025.parquet")
    df_short = pd.concat([s24, s25], ignore_index=True)
    
    model_dir_short = Path("studies/freeze_reduced_flip_model_artifacts/artifacts/short_bearish_flip_top25_current_reference")
    df_feats = pd.read_csv(model_dir_short / "feature_order.csv")
    feat_names = df_feats["feature_name"].tolist()
    
    model = joblib.load(model_dir_short / "model.joblib")
    df_short["score"] = model.predict_proba(df_short[feat_names])[:, 1]
    
    p99 = np.percentile(df_short["score"], 99.0) # Top 1%
    p95 = np.percentile(df_short["score"], 95.0) # Top 5%
    
    print(f"Short score 99th percentile cutoff (Top 1%): {p99:.4f}")
    print(f"Short score 95th percentile cutoff (Top 5%): {p95:.4f}")
    
    # Check sample rows
    top1_sample = df_short[df_short["score"] >= p99].head(5)
    top5_sample = df_short[(df_short["score"] >= p95) & (df_short["score"] < p99)].head(5)
    
    print("\n--- Top 1% Short Signals Sample (5 rows) ---")
    cols_to_show = [c for c in ["observation_time", "score", "regime_start_ns", "entry_px", "fill_px", "exit_ts", "hit_opposing_flip", "atr_at_entry"] if c in df_short.columns]
    print(top1_sample[cols_to_show].to_string())
    
    print("\n--- Top 5% Short Signals Sample (5 rows) ---")
    print(top5_sample[cols_to_show].to_string())


def main():
    check_candidate_directions()
    run_first_divergence_trace()


if __name__ == "__main__":
    main()
