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
    df["vwap_z_signed"] = ((df["entry_px_bar1"] - df["vwap"]) / df["entry_atr"].replace(0, 1.0)) * df["signal_direction"]
    df = df.dropna(subset=["mfe_before_flip", "mae_before_flip"])
    
    features = ["dist_ema3_atr", "dist_ema13_atr", "vwap_z_signed"]
    
    print(f"Loaded {len(df):,} trades.")
    
    for feat in features:
        print(f"\n=========================================")
        print(f"Feature: {feat}")
        print(f"=========================================")
        
        # Calculate deciles on full sample
        sub = df[[feat, "mfe_before_flip", "mae_before_flip"]].copy()
        sub[feat] = pd.to_numeric(sub[feat], errors="coerce")
        sub = sub.dropna()
        
        noise = np.random.normal(0, 1e-10, len(sub))
        sub["decile"] = pd.qcut(sub[feat] + noise, 10, labels=False, duplicates="drop") + 1
        
        # We want to print:
        # Decile | Count | Mean MFE | Mean MAE | P(MFE >= 1 & MAE < 1) | P(MFE >= 2 & MAE < 2) | P(MFE >= 3 & MAE < 3) | P(MAE >= 1) | P(MAE >= 2)
        print(f"{'Decile':<6} | {'Count':<6} | {'Mean MFE':<8} | {'Mean MAE':<8} | {'P(MFE>=1 & MAE<1)':<20} | {'P(MFE>=2 & MAE<2)':<20} | {'P(MAE>=1)':<10} | {'P(MAE>=2)':<10} | {'MFE/MAE':<8}")
        print("-" * 115)
        for d in range(1, 11):
            d_grp = sub[sub["decile"] == d]
            n_d = len(d_grp)
            mfe = d_grp["mfe_before_flip"].to_numpy()
            mae = d_grp["mae_before_flip"].to_numpy()
            
            m_mfe = np.mean(mfe)
            m_mae = np.mean(mae)
            
            p_1_clean = np.mean((mfe >= 1.0) & (mae < 1.0)) * 100
            p_2_clean = np.mean((mfe >= 2.0) & (mae < 2.0)) * 100
            
            p_mae_1 = np.mean(mae >= 1.0) * 100
            p_mae_2 = np.mean(mae >= 2.0) * 100
            
            ratio = m_mfe / max(m_mae, 0.01)
            
            print(f"{d:<6} | {n_d:<6,} | {m_mfe:<8.2f} | {m_mae:<8.2f} | {p_1_clean:<20.1f}% | {p_2_clean:<20.1f}% | {p_mae_1:<10.1f}% | {p_mae_2:<10.1f}% | {ratio:<8.2f}")

if __name__ == "__main__":
    main()
