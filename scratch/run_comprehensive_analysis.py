import os, sys, time
from pathlib import Path
import numpy as np
import pandas as pd
from scipy.stats import spearmanr

PROJECT_ROOT = Path("c:/Users/Scott McCarty/Projects/Nautilus Trader")
sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)

def compute_pf(pnl):
    wins = pnl[pnl > 0].sum()
    losses = abs(pnl[pnl < 0].sum())
    return wins / losses if losses > 0 else float("inf")

def run_analysis_for_target(df, target_col, target_name, is_pts=True):
    # Filter out missing values
    sub_df = df.dropna(subset=[target_col, "mfe_before_flip", "mae_before_flip"])
    
    features = [
        # Prior Regime
        "prior_regime_duration_bars",
        "prior_regime_total_return_atr",
        "prior_regime_total_return_points",
        "prior_regime_max_favorable_excursion",
        "prior_regime_max_adverse_excursion",
        "prior_regime_range_atr",
        "prior_regime_efficiency_ratio",
        "prior_regime_chop_ratio",
        "prior_regime_realized_vol",
        "prior_regime_mean_bar_range",
        "prior_regime_std_bar_range",
        # Compression
        "atr_percentile_30m",
        "rv_percentile",
        "range_percentile",
        "bb_width_percentile",
        "keltner_width_percentile",
        "volatility_contraction_ratio",
        "pre_signal_range_compression_3v10",
        "pre_signal_body_compression_3v10",
        "pre_signal_atr_ratio_3v10",
        "pre_signal_vol_compression_3v10",
        "tot_slow",
        "tot_med",
        # Distance / Stretch
        "dist_ema3",
        "dist_ema3_atr",
        "dist_ema13",
        "dist_ema13_atr",
        "vwap_z_signed",
        "vwap_z_abs",
        "dist_session_high",
        "dist_session_high_atr",
        "dist_session_low",
        "dist_session_low_atr",
        "dist_overnight_high",
        "dist_overnight_high_atr",
        "dist_overnight_low",
        "dist_overnight_low_atr",
        # Market Structure
        "or_position",
        "session_progress",
        "minutes_since_rth_open",
        "gap_size_raw",
        "gap_percentile",
        # Regime Persistence
        "regime_flips_last_30min",
        "regime_flips_last_60min",
        "avg_regime_duration_last_5",
        "consecutive_trend_bars_pre_flip",
        # HMM
        "kmeans_4_state"
    ]
    
    features = [f for f in features if f in sub_df.columns]
    
    results = []
    detailed_deciles = {}
    
    for feat in features:
        sub = sub_df[[feat, target_col, "mfe_before_flip", "mae_before_flip", "year"]].copy()
        sub[feat] = pd.to_numeric(sub[feat], errors="coerce")
        sub = sub.dropna()
        
        if len(sub) < 5000:
            continue
            
        # Overall Spearman IC
        ic_overall, _ = spearmanr(sub[feat], sub[target_col])
        if np.isnan(ic_overall):
            ic_overall = 0.0
            
        # Year-by-year Spearman ICs
        y_ics = []
        for yr in [2023, 2024, 2025, 2026]:
            grp = sub[sub["year"] == yr]
            if len(grp) > 100:
                ic_yr, _ = spearmanr(grp[feat], grp[target_col])
                y_ics.append(0.0 if np.isnan(ic_yr) else ic_yr)
            else:
                y_ics.append(0.0)
                
        # Stability Score = Mean IC / Std IC
        mean_ic = np.mean(y_ics)
        std_ic = np.std(y_ics)
        stability = mean_ic / std_ic if std_ic > 1e-5 else (mean_ic / 1e-5)
        
        # Count years with same sign as overall IC
        same_sign_years = sum(np.sign(ic) == np.sign(ic_overall) for ic in y_ics if ic != 0)
        
        # Decile ranking
        try:
            noise = np.random.normal(0, 1e-10, len(sub))
            sub["decile"] = pd.qcut(sub[feat] + noise, 10, labels=False, duplicates="drop") + 1
        except Exception:
            continue
            
        decile_summary = []
        decile_evs = []
        
        for d in range(1, 11):
            d_grp = sub[sub["decile"] == d]
            n_d = len(d_grp)
            if n_d == 0:
                decile_evs.append(0.0)
                continue
                
            g_wr = (d_grp[target_col] > 0).mean() * 100
            # If target is points, convert EV to USD (x20). If target is ATR, EV is in ATR units.
            g_ev = d_grp[target_col].mean() * (20.0 if is_pts else 1.0)
            g_pf = compute_pf(d_grp[target_col])
            mean_mfe = d_grp["mfe_before_flip"].mean()
            mean_mae = d_grp["mae_before_flip"].mean()
            reach_1 = (d_grp["mfe_before_flip"] >= 1.0).mean() * 100
            reach_2 = (d_grp["mfe_before_flip"] >= 2.0).mean() * 100
            reach_3 = (d_grp["mfe_before_flip"] >= 3.0).mean() * 100
            
            decile_summary.append({
                "decile": d,
                "count": n_d,
                "ev": g_ev,
                "pf": g_pf,
                "wr": g_wr,
                "mfe": mean_mfe,
                "mae": mean_mae,
                "reach_1": reach_1,
                "reach_2": reach_2,
                "reach_3": reach_3
            })
            
            decile_evs.append(g_ev)
            
        # Monotonicity Score
        decile_ranks = list(range(1, 11))
        monotonicity, _ = spearmanr(decile_ranks, decile_evs)
        if np.isnan(monotonicity):
            monotonicity = 0.0
        monotonicity = abs(monotonicity)
        
        # Find best decile
        best_d_idx = np.argmax(decile_evs)
        best_d = decile_summary[best_d_idx]
        
        results.append({
            "feature": feat,
            "spearman_ic": ic_overall,
            "monotonicity": monotonicity,
            "best_decile_pf": best_d["pf"],
            "best_decile_ev": best_d["ev"],
            "best_decile_num": best_d["decile"],
            "trade_count": len(sub),
            "stability_score": stability,
            "same_sign_years": same_sign_years,
            "y_ics": y_ics
        })
        
        detailed_deciles[feat] = pd.DataFrame(decile_summary)
        
    df_results = pd.DataFrame(results)
    df_results["abs_ic"] = df_results["spearman_ic"].abs()
    
    # Sort by Same Sign Years, then absolute IC, then monotonicity
    df_results = df_results.sort_values(
        by=["same_sign_years", "abs_ic", "monotonicity"],
        ascending=[False, False, False]
    ).reset_index(drop=True)
    
    return df_results, detailed_deciles

def main():
    t0 = time.time()
    ds_path = "scratch/bar1_conditioning_dataset.parquet"
    if not os.path.exists(ds_path):
        print(f"Error: {ds_path} not found.")
        return
        
    df = pd.read_parquet(ds_path)
    # Calculate VWAP stretch features dynamically
    df["vwap_z_signed"] = ((df["entry_px_bar1"] - df["vwap"]) / df["entry_atr"].replace(0, 1.0)) * df["signal_direction"]
    df["vwap_z_abs"] = df["vwap_z_signed"].abs()
    print(f"Loaded {len(df):,} trades and calculated VWAP distance features.")
    
    # Run analysis for both targets
    print("\n--- RUNNING ANALYSIS FOR RAW POINTS PNL ---")
    df_pts, deciles_pts = run_analysis_for_target(df, "regime_pnl_pts_bar1", "Points PnL", is_pts=True)
    
    print("\n--- RUNNING ANALYSIS FOR ATR-NORMALIZED PNL ---")
    df_atr, deciles_atr = run_analysis_for_target(df, "regime_pnl_atr_bar1", "ATR PnL", is_pts=False)
    
    # Write report directly to a Markdown file
    report_path = "scratch/comprehensive_conditioning_report.md"
    with open(report_path, "w", encoding="utf-8") as f:
        f.write("# Comprehensive Entry-Time Conditioning Study for Bar1-Confirmed Regime Flips\n\n")
        f.write(f"Generated at: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"Total bar1-confirmed trades analyzed: {len(df):,}\n\n")
        
        # Section 1: Points-based analysis
        f.write("## Section 1: Target = Raw Points PnL (`regime_pnl_pts_bar1`)\n\n")
        f.write("### Feature Ranking Table\n\n")
        f.write("| Feature | Spearman IC | Monotonicity | Best Decile PF | Best Decile EV ($) | Trade Count | Same Sign Years | Stability Score |\n")
        f.write("| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |\n")
        for idx, row in df_pts.iterrows():
            f.write(f"| {row['feature']} | {row['spearman_ic']:.4f} | {row['monotonicity']:.2f} | {row['best_decile_pf']:.2f} | ${row['best_decile_ev']:.2f} | {row['trade_count']:,} | {row['same_sign_years']}/4 | {row['stability_score']:.2f} |\n")
            
        f.write("\n### Top 10 Features Decile Breakdowns\n\n")
        for idx, row in df_pts.head(10).iterrows():
            feat = row["feature"]
            f.write(f"#### Feature: `{feat}` (Best Decile: {row['best_decile_num']})\n\n")
            f.write("| Decile | Count | Gross EV ($) | Gross PF | Win Rate (%) | Mean MFE (ATR) | Mean MAE (ATR) | % 1 ATR | % 2 ATR | % 3 ATR |\n")
            f.write("| :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |\n")
            d_df = deciles_pts[feat]
            for d_idx, d_row in d_df.iterrows():
                f.write(f"| {int(d_row['decile'])} | {int(d_row['count']):,} | ${d_row['ev']:.2f} | {d_row['pf']:.2f} | {d_row['wr']:.1f}% | {d_row['mfe']:.2f} | {d_row['mae']:.2f} | {d_row['reach_1']:.1f}% | {d_row['reach_2']:.1f}% | {d_row['reach_3']:.1f}% |\n")
            f.write("\n")
            
        # Section 2: ATR-based analysis
        f.write("## Section 2: Target = ATR-Normalized PnL (`regime_pnl_atr_bar1`)\n\n")
        f.write("### Feature Ranking Table\n\n")
        f.write("| Feature | Spearman IC | Monotonicity | Best Decile PF | Best Decile EV (ATR) | Trade Count | Same Sign Years | Stability Score |\n")
        f.write("| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |\n")
        for idx, row in df_atr.iterrows():
            f.write(f"| {row['feature']} | {row['spearman_ic']:.4f} | {row['monotonicity']:.2f} | {row['best_decile_pf']:.2f} | {row['best_decile_ev']:.2f} | {row['trade_count']:,} | {row['same_sign_years']}/4 | {row['stability_score']:.2f} |\n")
            
        f.write("\n### Top 10 Features Decile Breakdowns\n\n")
        for idx, row in df_atr.head(10).iterrows():
            feat = row["feature"]
            f.write(f"#### Feature: `{feat}` (Best Decile: {row['best_decile_num']})\n\n")
            f.write("| Decile | Count | Gross EV (ATR) | Gross PF | Win Rate (%) | Mean MFE (ATR) | Mean MAE (ATR) | % 1 ATR | % 2 ATR | % 3 ATR |\n")
            f.write("| :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |\n")
            d_df = deciles_atr[feat]
            for d_idx, d_row in d_df.iterrows():
                f.write(f"| {int(d_row['decile'])} | {int(d_row['count']):,} | {d_row['ev']:.2f} | {d_row['pf']:.2f} | {d_row['wr']:.1f}% | {d_row['mfe']:.2f} | {d_row['mae']:.2f} | {d_row['reach_1']:.1f}% | {d_row['reach_2']:.1f}% | {d_row['reach_3']:.1f}% |\n")
            f.write("\n")
            
    print(f"\nSuccessfully generated {report_path} in {(time.time()-t0)/60:.2f} min.")

if __name__ == "__main__":
    main()
