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
    
    print(f"Loaded {len(df):,} trades and computed VWAP features.")
    
    # Target features for study
    features = [
        "dist_ema13_atr",
        "dist_ema3_atr",
        "keltner_width_percentile",
        "atr_percentile_30m",
        "rv_percentile",
        "range_percentile",
        "dist_overnight_low_atr",
        "dist_overnight_high_atr",
        "vwap_z_abs",
        "vwap_z_signed",
        # Extra high stability/IC features from prior study
        "dist_ema3",
        "dist_ema13",
        "bb_width_percentile",
        "volatility_contraction_ratio",
        "kmeans_4_state",
        "dist_session_high",
        "dist_session_low_atr",
        "dist_overnight_high",
        "prior_regime_max_favorable_excursion",
        "prior_regime_range_atr"
    ]
    
    # Filter for columns present in df
    features = [f for f in features if f in df.columns]
    
    # Audit target variables (MFE/MAE are in ATR units)
    # We drop rows where excursion data is missing
    df = df.dropna(subset=["mfe_before_flip", "mae_before_flip"])
    
    results = {}
    
    # We will evaluate across the full sample and individual years 2023, 2024, 2025, 2026
    cohorts = {
        "Full Sample": df,
        "2023": df[df["year"] == 2023],
        "2024": df[df["year"] == 2024],
        "2025": df[df["year"] == 2025],
        "2026": df[df["year"] == 2026]
    }
    
    # For monotonicity evaluation, we will track decile-level metrics across features
    feature_monotonicity_metrics = []
    
    for feat in features:
        results[feat] = {}
        
        for name, cohort in cohorts.items():
            if len(cohort) < 500:
                continue
                
            sub = cohort[[feat, "mfe_before_flip", "mae_before_flip"]].copy()
            sub[feat] = pd.to_numeric(sub[feat], errors="coerce")
            sub = sub.dropna()
            
            if len(sub) < 100:
                continue
                
            # Assign deciles (1 to 10)
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
                    
                mfe_mean = d_grp["mfe_before_flip"].mean()
                mfe_median = d_grp["mfe_before_flip"].median()
                mae_mean = d_grp["mae_before_flip"].mean()
                mae_median = d_grp["mae_before_flip"].median()
                
                p_0p5 = (d_grp["mfe_before_flip"] >= 0.5).mean() * 100
                p_1p0 = (d_grp["mfe_before_flip"] >= 1.0).mean() * 100
                p_1p5 = (d_grp["mfe_before_flip"] >= 1.5).mean() * 100
                p_2p0 = (d_grp["mfe_before_flip"] >= 2.0).mean() * 100
                p_3p0 = (d_grp["mfe_before_flip"] >= 3.0).mean() * 100
                
                opp_ratio = mfe_mean / max(mae_mean, 0.01)
                opp_score = ((d_grp["mfe_before_flip"] >= 2.0) & (d_grp["mae_before_flip"] <= 1.0)).mean() * 100
                runner_score = (d_grp["mfe_before_flip"] >= 3.0).mean() * 100
                fakeout_score = (d_grp["mfe_before_flip"] < 0.5).mean() * 100
                
                deciles_data.append({
                    "decile": d,
                    "count": n_d,
                    "mfe_mean": mfe_mean,
                    "mfe_median": mfe_median,
                    "mae_mean": mae_mean,
                    "mae_median": mae_median,
                    "reach_0p5": p_0p5,
                    "reach_1p0": p_1p0,
                    "reach_1p5": p_1p5,
                    "reach_2p0": p_2p0,
                    "reach_3p0": p_3p0,
                    "opp_ratio": opp_ratio,
                    "opp_score": opp_score,
                    "runner_score": runner_score,
                    "fakeout_score": fakeout_score
                })
                
            results[feat][name] = pd.DataFrame(deciles_data)
            
        # Monotonicity evaluation on Full Sample
        if "Full Sample" in results[feat]:
            fs_df = results[feat]["Full Sample"]
            if len(fs_df) == 10:
                decile_ranks = list(range(1, 11))
                
                mono_mfe, _ = spearmanr(decile_ranks, fs_df["mfe_mean"])
                mono_reach_2, _ = spearmanr(decile_ranks, fs_df["reach_2p0"])
                mono_reach_3, _ = spearmanr(decile_ranks, fs_df["reach_3p0"])
                mono_opp_ratio, _ = spearmanr(decile_ranks, fs_df["opp_ratio"])
                
                # Check stability across years: do the years 2023-2026 have the same sign of correlation as overall?
                # Let's count how many years have the same sign for mono_mfe
                same_sign_count = 0
                y_corrs = []
                for yr in ["2023", "2024", "2025", "2026"]:
                    if yr in results[feat]:
                        yr_df = results[feat][yr]
                        if len(yr_df) == 10:
                            yr_corr, _ = spearmanr(list(range(1, 11)), yr_df["mfe_mean"])
                            y_corrs.append(yr_corr)
                            if np.sign(yr_corr) == np.sign(mono_mfe) and not np.isnan(yr_corr) and not np.isnan(mono_mfe):
                                same_sign_count += 1
                                
                feature_monotonicity_metrics.append({
                    "feature": feat,
                    "mono_mfe": mono_mfe,
                    "mono_reach_2": mono_reach_2,
                    "mono_reach_3": mono_reach_3,
                    "mono_opp_ratio": mono_opp_ratio,
                    "same_sign_years": same_sign_count,
                    "y_corrs": y_corrs
                })
                
    df_mono = pd.DataFrame(feature_monotonicity_metrics)
    df_mono["abs_mono_mfe"] = df_mono["mono_mfe"].abs()
    df_mono = df_mono.sort_values(by=["same_sign_years", "abs_mono_mfe"], ascending=[False, False]).reset_index(drop=True)
    
    # Generate report
    report_path = "scratch/opportunity_audit_report.md"
    with open(report_path, "w", encoding="utf-8") as f:
        f.write("# Opportunity Quality vs Terminal Expectancy Audit Report\n\n")
        f.write(f"Generated at: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"Total bar1-confirmed trades analyzed: {len(df):,}\n\n")
        
        f.write("## Section 1: Monotonicity & Stability Table\n\n")
        f.write("This table ranks features by the Spearman correlation of their decile ranks with the mean MFE (monotonicity of excursion distance) and measures stability (same sign of correlation) across years 2023–2026.\n\n")
        f.write("| Feature | MFE Monotonicity | 2 ATR Hit Mono | 3 ATR Hit Mono | Opp Ratio Mono | Same Sign Years | Yearly Correlations (23-26) |\n")
        f.write("| :--- | :---: | :---: | :---: | :---: | :---: | :--- |\n")
        for idx, row in df_mono.iterrows():
            f.write(f"| `{row['feature']}` | {row['mono_mfe']:+.4f} | {row['mono_reach_2']:+.4f} | {row['mono_reach_3']:+.4f} | {row['mono_opp_ratio']:+.4f} | {row['same_sign_years']}/4 | {[f'{x:+.2f}' for x in row['y_corrs']]} |\n")
            
        f.write("\n## Section 2: Detailed Decile Breakdown for Top Excursion-Predictive Features\n\n")
        
        # Let's print decile tables for top 5 features
        for idx, row in df_mono.head(5).iterrows():
            feat = row["feature"]
            f.write(f"### Feature: `{feat}`\n\n")
            
            for cohort_name in ["Full Sample", "2023", "2024", "2025", "2026"]:
                if cohort_name in results[feat]:
                    f.write(f"#### {cohort_name}\n\n")
                    f.write("| Decile | Count | Mean MFE | Med MFE | Mean MAE | Med MAE | % 0.5 ATR | % 1.0 ATR | % 2.0 ATR | % 3.0 ATR | Opp Ratio | Opp Score | Runner % | Fakeout % |\n")
                    f.write("| :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |\n")
                    c_df = results[feat][cohort_name]
                    for d_idx, d_row in c_df.iterrows():
                        f.write(f"| {int(d_row['decile'])} | {int(d_row['count']):,} | {d_row['mfe_mean']:.2f} | {d_row['mfe_median']:.2f} | {d_row['mae_mean']:.2f} | {d_row['mae_median']:.2f} | {d_row['reach_0p5']:.1f}% | {d_row['reach_1p0']:.1f}% | {d_row['reach_2p0']:.1f}% | {d_row['reach_3p0']:.1f}% | {d_row['opp_ratio']:.2f} | {d_row['opp_score']:.1f}% | {d_row['runner_score']:.1f}% | {d_row['fakeout_score']:.1f}% |\n")
                    f.write("\n")
                    
        f.write("## Section 3: Summary of Features with No Excursion Predictability\n\n")
        f.write("The following features show zero or near-zero monotonicity (Spearman correlation < 0.30) or complete instability across years, indicating opportunity quality is uniformly distributed across their values:\n\n")
        for idx, row in df_mono.iterrows():
            if abs(row['mono_mfe']) < 0.30 or row['same_sign_years'] < 3:
                f.write(f"*   `{row['feature']}`: MFE Monotonicity = {row['mono_mfe']:+.4f}, Stable Years = {row['same_sign_years']}/4\n")
                
    print(f"\nAudit report successfully compiled to {report_path} in {(time.time()-t0)/60:.2f} minutes.")

if __name__ == "__main__":
    main()
