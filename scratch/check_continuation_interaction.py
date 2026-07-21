import os, sys, time
from pathlib import Path
import numpy as np
import pandas as pd

PROJECT_ROOT = Path("c:/Users/Scott McCarty/Projects/Nautilus Trader")
sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)

def main():
    ds_path = "scratch/bar1_conditioning_dataset.parquet"
    if not os.path.exists(ds_path):
        print(f"Error: {ds_path} not found.")
        return
        
    df = pd.read_parquet(ds_path)
    
    # Analyze dist_ema3_atr
    feat_col = "dist_ema3_atr"
    sub = df[[feat_col, "mfe_before_flip", "pnl_60s_atr", "time_to_0p5_atr"]].copy()
    sub[feat_col] = pd.to_numeric(sub[feat_col], errors="coerce")
    sub = sub.dropna(subset=[feat_col, "mfe_before_flip"])
    
    p20 = sub[feat_col].quantile(0.20)
    p80 = sub[feat_col].quantile(0.80)
    
    low_cohort = sub[sub[feat_col] <= p20].copy()
    high_cohort = sub[sub[feat_col] >= p80].copy()
    
    scale_low_mfe = low_cohort["mfe_before_flip"].mean()
    scale_high_mfe = high_cohort["mfe_before_flip"].mean()
    gamma = scale_high_mfe / scale_low_mfe
    
    print(f"Mean MFE - Low Cohort: {scale_low_mfe:.4f}")
    print(f"Mean MFE - High Cohort: {scale_high_mfe:.4f}")
    print(f"Empirical Scale Factor (Gamma): {gamma:.4f}")
    
    # 1. Actual High Cohort: P(MFE >= 2.0 | MFE >= 0.5)
    reached_05_high = high_cohort[high_cohort["mfe_before_flip"] >= 0.5]
    actual_high_cond_p = (reached_05_high["mfe_before_flip"] >= 2.0).mean() * 100
    
    # 2. Predicted High Cohort from Low Cohort using Scale Shift Model:
    # P(MFE_low >= 2.0 / Gamma | MFE_low >= 0.5 / Gamma)
    target_thresh = 2.0 / gamma
    start_thresh = 0.5 / gamma
    
    reached_start_low = low_cohort[low_cohort["mfe_before_flip"] >= start_thresh]
    predicted_high_cond_p = (reached_start_low["mfe_before_flip"] >= target_thresh).mean() * 100
    
    print(f"\nConditional Probability P(MFE >= 2.0 | MFE >= 0.5):")
    print(f"  Actual High Cohort            : {actual_high_cond_p:.2f}%")
    print(f"  Predicted by Scale Shift Model: {predicted_high_cond_p:.2f}%")
    print(f"  Difference (Actual - Pred)    : {actual_high_cond_p - predicted_high_cond_p:+.2f}%")
    
    # Let's check if there is an interaction with the 60s PnL gate.
    # We want to check P(MFE >= 2.0 | PnL_60s >= 0.20) for High Cohort
    reached_gate_high = high_cohort[high_cohort["pnl_60s_atr"] >= 0.20]
    actual_high_gate_p = (reached_gate_high["mfe_before_flip"] >= 2.0).mean() * 100
    
    # Scale Shift Model prediction: P(MFE_low >= 2.0/Gamma | PnL_60s_low >= 0.20/Gamma)
    predicted_gate_high = (low_cohort[low_cohort["pnl_60s_atr"] >= 0.20/gamma]["mfe_before_flip"] >= 2.0/gamma).mean() * 100
    
    print(f"\nGate Performance P(MFE >= 2.0 | PnL_60s >= 0.20 ATR):")
    print(f"  Actual High Cohort            : {actual_high_gate_p:.2f}%")
    print(f"  Predicted by Scale Shift Model: {predicted_gate_high:.2f}%")
    print(f"  Difference (Actual - Pred)    : {actual_high_gate_p - predicted_gate_high:+.2f}%")

if __name__ == "__main__":
    main()
