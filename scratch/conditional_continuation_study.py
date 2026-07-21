import os, sys, time
from pathlib import Path
import numpy as np
import pandas as pd
from scipy.stats import spearmanr

PROJECT_ROOT = Path("c:/Users/Scott McCarty/Projects/Nautilus Trader")
sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)

def main():
    t0 = time.time()
    ds_path = "scratch/bar1_conditioning_dataset.parquet"
    if not os.path.exists(ds_path):
        print(f"Error: {ds_path} not found.")
        return
        
    df = pd.read_parquet(ds_path)
    
    # Calculate VWAP features dynamically
    df["vwap_z_signed"] = ((df["entry_px_bar1"] - df["vwap"]) / df["entry_atr"].replace(0, 1.0)) * df["signal_direction"]
    df["vwap_z_abs"] = df["vwap_z_signed"].abs()
    
    df = df.dropna(subset=["mfe_before_flip", "mae_before_flip"])
    print(f"Loaded {len(df):,} trades and clean excursion paths.")
    
    features = ["dist_ema3_atr", "dist_ema13_atr", "vwap_z_signed"]
    
    cohorts = {
        "Full Sample": df,
        "2023": df[df["year"] == 2023],
        "2024": df[df["year"] == 2024],
        "2025": df[df["year"] == 2025],
        "2026": df[df["year"] == 2026]
    }
    
    results = {}
    
    for feat in features:
        results[feat] = {}
        for name, cohort in cohorts.items():
            if len(cohort) < 100:
                continue
                
            sub = cohort[[feat, "mfe_before_flip"]].copy()
            sub[feat] = pd.to_numeric(sub[feat], errors="coerce")
            sub = sub.dropna()
            
            try:
                noise = np.random.normal(0, 1e-10, len(sub))
                sub["decile"] = pd.qcut(sub[feat] + noise, 10, labels=False, duplicates="drop") + 1
            except Exception:
                continue
                
            deciles_data = []
            for d in range(1, 11):
                d_grp = sub[sub["decile"] == d]
                n_d = len(d_grp)
                if n_d == 0:
                    continue
                    
                # Excursion checks
                mfe = d_grp["mfe_before_flip"].to_numpy()
                
                # P(MFE >= 1 ATR)
                n_1 = np.sum(mfe >= 1.0)
                p_1 = (n_1 / n_d) * 100 if n_d > 0 else 0.0
                
                # P(MFE >= 2 | MFE >= 1)
                n_2 = np.sum(mfe >= 2.0)
                p_2 = (n_2 / n_1) * 100 if n_1 > 0 else 0.0
                
                # P(MFE >= 3 | MFE >= 2)
                n_3 = np.sum(mfe >= 3.0)
                p_3 = (n_3 / n_2) * 100 if n_2 > 0 else 0.0
                
                # P(MFE >= 4 | MFE >= 3)
                n_4 = np.sum(mfe >= 4.0)
                p_4 = (n_4 / n_3) * 100 if n_3 > 0 else 0.0
                
                # Median additional excursion after each threshold
                # Med(MFE - K) for trades that reach >= K
                mfe_1 = mfe[mfe >= 1.0]
                med_add_1 = np.median(mfe_1 - 1.0) if len(mfe_1) > 0 else 0.0
                
                mfe_2 = mfe[mfe >= 2.0]
                med_add_2 = np.median(mfe_2 - 2.0) if len(mfe_2) > 0 else 0.0
                
                mfe_3 = mfe[mfe >= 3.0]
                med_add_3 = np.median(mfe_3 - 3.0) if len(mfe_3) > 0 else 0.0
                
                deciles_data.append({
                    "decile": d,
                    "count": n_d,
                    "p_1": p_1,
                    "p_2": p_2,
                    "p_3": p_3,
                    "p_4": p_4,
                    "med_add_1": med_add_1,
                    "med_add_2": med_add_2,
                    "med_add_3": med_add_3
                })
                
            results[feat][name] = pd.DataFrame(deciles_data)
            
    # Write study report
    report_path = "scratch/conditional_continuation_report.md"
    with open(report_path, "w", encoding="utf-8") as f:
        f.write("# Conditional Continuation Probabilities Study\n\n")
        f.write(f"Generated at: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write("Evaluation of conditional probabilities and median additional excursions by stretch decile and year.\n\n")
        
        for feat in features:
            f.write(f"## Feature: `{feat}`\n\n")
            
            for cohort_name in ["Full Sample", "2023", "2024", "2025", "2026"]:
                if cohort_name in results[feat]:
                    f.write(f"### cohort: {cohort_name}\n\n")
                    f.write("| Decile | Count | P(MFE >= 1) | P(MFE >= 2 \| MFE >= 1) | P(MFE >= 3 \| MFE >= 2) | P(MFE >= 4 \| MFE >= 3) | Med Add Excursion (>=1) | Med Add Excursion (>=2) | Med Add Excursion (>=3) |\n")
                    f.write("| :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |\n")
                    c_df = results[feat][cohort_name]
                    for d_idx, d_row in c_df.iterrows():
                        f.write(f"| {int(d_row['decile'])} | {int(d_row['count']):,} | {d_row['p_1']:.1f}% | {d_row['p_2']:.1f}% | {d_row['p_3']:.1f}% | {d_row['p_4']:.1f}% | {d_row['med_add_1']:.2f} ATR | {d_row['med_add_2']:.2f} ATR | {d_row['med_add_3']:.2f} ATR |\n")
                    f.write("\n")
                    
    print(f"\nConditional continuation report compiled to {report_path} in {(time.time()-t0)/60:.2f} minutes.")

if __name__ == "__main__":
    main()
