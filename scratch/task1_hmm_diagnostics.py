"""Task 1: HMM State-Identity Confound Analysis."""
import pandas as pd
import numpy as np
from pathlib import Path

PROJECT_ROOT = Path("c:/Users/Scott McCarty/Projects/Nautilus Trader")
STATES_PATH = PROJECT_ROOT / "studies/regime_classification/results/states_nq_1m.parquet"

def main():
    print(f"Loading HMM states from {STATES_PATH}")
    df = pd.read_parquet(STATES_PATH)
    
    # Filter for In-Sample training data only (2020-2022) with valid predictions
    is_df = df[df["year"].isin([2020, 2021, 2022])].copy()
    print(f"Total rows in In-Sample dataset: {len(is_df):,}")
    
    # Check if 'hmm_4' exists in the columns
    if "hmm_4" not in is_df.columns:
        print("Error: hmm_4 not found in states parquet!")
        return
        
    valid_is = is_df[is_df["hmm_4"] >= 0]
    print(f"Valid IS rows for hmm_4: {len(valid_is):,}")
    
    # Target features
    features = ["rv_300s", "range_atr_60s", "efficiency_300s", "chop_ratio_300s"]
    
    # Compute mean for each feature in each state
    state_means = valid_is.groupby("hmm_4")[features].mean()
    print("\nMean feature values per state:")
    print(state_means.to_string())
    
    # Compute z-score across states (population std)
    z_scores = pd.DataFrame(index=state_means.index)
    for f in features:
        mu = state_means[f].mean()
        std = state_means[f].std(ddof=0) # population standard deviation
        z_scores[f] = (state_means[f] - mu) / std
        
    print("\nZ-scores of feature means across states (population std):")
    print(z_scores.to_string())
    
    # Compute signature score: z(rv_300s) + z(range_atr_60s) + z(efficiency_300s) - z(chop_ratio_300s)
    z_scores["score"] = (
        z_scores["rv_300s"] + 
        z_scores["range_atr_60s"] + 
        z_scores["efficiency_300s"] - 
        z_scores["chop_ratio_300s"]
    )
    
    print("\nSignature scores per state:")
    print(z_scores[["score"]].to_string())
    
    max_state = z_scores["score"].idxmax()
    max_score = z_scores["score"].max()
    print(f"\nMax-signature state is index: {max_state} with score {max_score:.4f}")
    
    is_state_3_max = (max_state == 3)
    print(f"Is static state 3 the max-signature state? {'YES' if is_state_3_max else 'NO'}")

if __name__ == "__main__":
    main()
