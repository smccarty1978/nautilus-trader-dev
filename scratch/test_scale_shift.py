import os, sys, time
from pathlib import Path
import numpy as np
import pandas as pd
from scipy.stats import ks_2samp

PROJECT_ROOT = Path("c:/Users/Scott McCarty/Projects/Nautilus Trader")
sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)

def main():
    ds_path = "scratch/bar1_conditioning_dataset.parquet"
    if not os.path.exists(ds_path):
        print(f"Error: {ds_path} not found.")
        return
        
    df = pd.read_parquet(ds_path)
    df["vwap_z_signed"] = ((df["entry_px_bar1"] - df["vwap"]) / df["entry_atr"].replace(0, 1.0)) * df["signal_direction"]
    df = df.dropna(subset=["mfe_before_flip", "mae_before_flip"])
    
    features = ["dist_ema3_atr", "dist_ema13_atr", "vwap_z_signed"]
    
    for feat in features:
        print(f"\n=========================================")
        print(f"Feature: {feat}")
        print(f"=========================================")
        
        sub = df[[feat, "mfe_before_flip", "mae_before_flip"]].copy()
        sub[feat] = pd.to_numeric(sub[feat], errors="coerce")
        sub = sub.dropna()
        
        noise = np.random.normal(0, 1e-10, len(sub))
        sub["decile"] = pd.qcut(sub[feat] + noise, 10, labels=False, duplicates="drop") + 1
        
        d1 = sub[sub["decile"] == 1]
        d10 = sub[sub["decile"] == 10]
        
        # Scale factor using mean MFE
        scale_d1_mfe = d1["mfe_before_flip"].mean()
        scale_d10_mfe = d10["mfe_before_flip"].mean()
        
        # Scale factor using mean MAE
        scale_d1_mae = d1["mae_before_flip"].mean()
        scale_d10_mae = d10["mae_before_flip"].mean()
        
        print(f"Decile 1  - Mean MFE: {scale_d1_mfe:.3f}, Mean MAE: {scale_d1_mae:.3f}")
        print(f"Decile 10 - Mean MFE: {scale_d10_mfe:.3f}, Mean MAE: {scale_d10_mae:.3f}")
        print(f"MFE Scale Factor (D10 / D1): {scale_d10_mfe / scale_d1_mfe:.3f}")
        print(f"MAE Scale Factor (D10 / D1): {scale_d10_mae / scale_d1_mae:.3f}")
        
        # Normalize by respective mean MFEs
        mfe_d1_norm = d1["mfe_before_flip"] / scale_d1_mfe
        mfe_d10_norm = d10["mfe_before_flip"] / scale_d10_mfe
        
        mae_d1_norm = d1["mae_before_flip"] / scale_d1_mfe
        mae_d10_norm = d10["mae_before_flip"] / scale_d10_mfe
        
        # KS Test for MFE distribution equivalence after scaling
        ks_mfe_stat, ks_mfe_p = ks_2samp(mfe_d1_norm, mfe_d10_norm)
        # KS Test for MAE distribution equivalence after scaling
        ks_mae_stat, ks_mae_p = ks_2samp(mae_d1_norm, mae_d10_norm)
        
        print(f"KS Test for Normalized MFE: stat={ks_mfe_stat:.4f}, p-value={ks_mfe_p:.4f}")
        print(f"KS Test for Normalized MAE: stat={ks_mae_stat:.4f}, p-value={ks_mae_p:.4f}")
        
        # If p-value > 0.05, we fail to reject the null hypothesis that they are from the same distribution.
        # This confirms a pure scale shift.
        if ks_mfe_p > 0.05 and ks_mae_p > 0.05:
            print("Verdict: Confirmed pure scale shift (Symmetric Volatility). Distribution shape is statistically identical.")
        else:
            print("Verdict: Statistically significant shape difference. There may be asymmetric drift/continuation.")
            
        # Let's also check the probability of MFE >= 2.0 * mean MFE vs MAE >= 2.0 * mean MFE
        print(f"Decile 1  - P(MFE >= 1.5*Mean): {np.mean(mfe_d1_norm >= 1.5)*100:.1f}%, P(MAE >= 1.5*Mean): {np.mean(mae_d1_norm >= 1.5)*100:.1f}%")
        print(f"Decile 10 - P(MFE >= 1.5*Mean): {np.mean(mfe_d10_norm >= 1.5)*100:.1f}%, P(MAE >= 1.5*Mean): {np.mean(mae_d10_norm >= 1.5)*100:.1f}%")

if __name__ == "__main__":
    main()
