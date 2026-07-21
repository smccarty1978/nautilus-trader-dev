import os, sys, time
from pathlib import Path
import numpy as np
import pandas as pd
from scipy.stats import spearmanr

PROJECT_ROOT = Path("c:/Users/Scott McCarty/Projects/Nautilus Trader")
sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)

def compute_pf(pnl_pts):
    wins = pnl_pts[pnl_pts > 0].sum()
    losses = abs(pnl_pts[pnl_pts < 0].sum())
    return wins / losses if losses > 0 else float("inf")

def main():
    t0 = time.time()
    
    # Load dataset
    ds_path = "scratch/bar1_conditioning_dataset.parquet"
    if not os.path.exists(ds_path):
        print(f"Error: {ds_path} not found.")
        return
        
    df = pd.read_parquet(ds_path)
    
    # Drop rows missing critical outcome metrics
    df = df.dropna(subset=["regime_pnl_pts_bar1", "mfe_before_flip", "mae_before_flip"])
    
    print(f"Loaded enriched dataset with {len(df):,} bar1-confirmed trades.")
    
    # Define feature set to evaluate
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
    
    # Filter features to only those present in columns
    features = [f for f in features if f in df.columns]
    print(f"Evaluating {len(features)} entry-time conditioning features.")
    
    results = []
    detailed_deciles = {}
    
    for feat in features:
        # Clean feature values
        sub = df[[feat, "regime_pnl_pts_bar1", "mfe_before_flip", "mae_before_flip", "year"]].copy()
        sub[feat] = pd.to_numeric(sub[feat], errors="coerce")
        sub = sub.dropna()
        
        if len(sub) < 5000:
            continue # skip features with too few observations
            
        # 1. Compute overall Spearman IC
        ic_overall, _ = spearmanr(sub[feat], sub["regime_pnl_pts_bar1"])
        
        # 2. Compute year-by-year Spearman ICs (2023, 2024, 2025, 2026)
        y_ics = []
        for yr in [2023, 2024, 2025, 2026]:
            grp = sub[sub["year"] == yr]
            if len(grp) > 100:
                ic_yr, _ = spearmanr(grp[feat], grp["regime_pnl_pts_bar1"])
                y_ics.append(ic_yr)
            else:
                y_ics.append(0.0)
                
        # 3. Calculate Stability Score = Mean IC / Std IC (Sharpe-like ratio across years)
        mean_ic = np.mean(y_ics)
        std_ic = np.std(y_ics)
        stability = mean_ic / std_ic if std_ic > 1e-5 else (mean_ic / 1e-5)
        
        # Count years with same sign as overall IC
        same_sign_years = sum(np.sign(ic) == np.sign(ic_overall) for ic in y_ics)
        
        # 4. Decile ranking
        # Assign deciles (1 to 10) based on ranking
        try:
            # Add small random noise to handle duplicates (e.g. integer state features)
            noise = np.random.normal(0, 1e-10, len(sub))
            sub["decile"] = pd.qcut(sub[feat] + noise, 10, labels=False, duplicates="drop") + 1
        except Exception as e:
            # Fallback if qcut fails
            continue
            
        # Compute decile metrics
        decile_summary = []
        decile_evs = []
        decile_pfs = []
        
        for d in range(1, 11):
            d_grp = sub[sub["decile"] == d]
            n_d = len(d_grp)
            if n_d == 0:
                decile_evs.append(0.0)
                decile_pfs.append(0.0)
                continue
                
            g_wr = (d_grp["regime_pnl_pts_bar1"] > 0).mean() * 100
            g_ev = d_grp["regime_pnl_pts_bar1"].mean() * 20.0
            g_pf = compute_pf(d_grp["regime_pnl_pts_bar1"])
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
            decile_pfs.append(g_pf)
            
        # 5. Compute Monotonicity Score: Spearman correlation between decile rank and EV
        decile_ranks = list(range(1, 11))
        monotonicity, _ = spearmanr(decile_ranks, decile_evs)
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
    
    # Calculate ranking score:
    # A feature is good if it has high stability, same_sign_years >= 3, and high monotonicity
    # Let's sort primarily by same_sign_years (stability across years), then absolute Spearman IC, then monotonicity
    df_results["abs_ic"] = df_results["spearman_ic"].abs()
    df_results = df_results.sort_values(
        by=["same_sign_years", "abs_ic", "monotonicity"],
        ascending=[False, False, False]
    ).reset_index(drop=True)
    
    print("\n" + "="*95)
    print("  FEATURE RANKING TABLE (Sorted by Stability and Spearman IC)")
    print("="*95)
    print("| Feature | Spearman IC | Monotonicity | Best Decile PF | Best Decile EV | Trade Count | Same Sign Years | Stability Score |")
    print("| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |")
    for idx, row in df_results.iterrows():
        print(f"| {row['feature']:<30} | {row['spearman_ic']:>11.4f} | {row['monotonicity']:>12.2f} | {row['best_decile_pf']:>14.2f} | ${row['best_decile_ev']:>13.2f} | {row['trade_count']:<11,} | {row['same_sign_years']:^15} | {row['stability_score']:>15.2f} |")
        
    # Top 20 features
    print("\n" + "="*80)
    print("  TOP 20 STABLE CONDITIONING FEATURES")
    print("="*80)
    for idx, row in df_results.head(20).iterrows():
        print(f"{idx+1:2d}. {row['feature']:<35} | Overall IC: {row['spearman_ic']:>7.4f} | Years IC: {[f'{x:+.4f}' for x in row['y_ics']]} | Sign Years: {row['same_sign_years']}/4")
        
    # Detailed Decile Charts for top 3 features
    print("\n" + "="*95)
    print("  DETAILED DECILE BREAKDOWN FOR TOP 3 STABLE FEATURES")
    print("="*95)
    for idx, row in df_results.head(3).iterrows():
        feat = row["feature"]
        print(f"\nFeature: {feat} (Best Decile: {row['best_decile_num']})")
        print("| Decile | Count | Gross EV ($) | Gross PF | Win Rate (%) | Mean MFE (ATR) | Mean MAE (ATR) | % 1 ATR | % 2 ATR | % 3 ATR |")
        print("| :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |")
        d_df = detailed_deciles[feat]
        for d_idx, d_row in d_df.iterrows():
            print(f"| {int(d_row['decile']):^6} | {int(d_row['count']):<5,} | ${d_row['ev']:>10.2f} | {d_row['pf']:>8.2f} | {d_row['wr']:>11.1f}% | {d_row['mfe']:>13.2f} | {d_row['mae']:>13.2f} | {d_row['reach_1']:>6.1f}% | {d_row['reach_2']:>6.1f}% | {d_row['reach_3']:>6.1f}% |")
            
    # Year-by-Year validation for the top 3 features
    print("\n" + "="*95)
    print("  YEAR-BY-YEAR VALIDATION FOR TOP 3 FEATURES (Best Decile Performance)")
    print("="*95)
    for idx, row in df_results.head(3).iterrows():
        feat = row["feature"]
        best_decile = row["best_decile_num"]
        print(f"\nFeature: {feat} | Best Decile: {best_decile}")
        print("| Year | Total Trades | Decile Trades | Gross WR% | Gross PF | Gross EV ($) | Net PnL ($) |")
        print("| :--- | :---: | :---: | :---: | :---: | :---: | :---: |")
        
        # Load details for that feature
        sub = df[[feat, "regime_pnl_pts_bar1", "year"]].copy()
        sub[feat] = pd.to_numeric(sub[feat], errors="coerce")
        sub = sub.dropna()
        noise = np.random.normal(0, 1e-10, len(sub))
        sub["decile"] = pd.qcut(sub[feat] + noise, 10, labels=False, duplicates="drop") + 1
        
        for yr in [2020, 2021, 2022, 2023, 2024, 2025, 2026]:
            yr_total = sub[sub["year"] == yr]
            yr_decile = yr_total[yr_total["decile"] == best_decile]
            n_tot = len(yr_total)
            n_dec = len(yr_decile)
            if n_dec == 0:
                print(f"| {yr} | {n_tot:<12,} | 0 | - | - | $0.00 | $0.00 |")
                continue
            wr = (yr_decile["regime_pnl_pts_bar1"] > 0).mean() * 100
            pf = compute_pf(yr_decile["regime_pnl_pts_bar1"])
            ev = yr_decile["regime_pnl_pts_bar1"].mean() * 20.0
            net_pnl = (yr_decile["regime_pnl_pts_bar1"].sum() * 20.0) - (n_dec * 10.0) # applying $10 friction
            print(f"| {yr} | {n_tot:<12,} | {n_dec:<13,} | {wr:>8.1f}% | {pf:>8.2f} | ${ev:>10.2f} | ${net_pnl:>+10,.2f} |")
            
    print(f"\n[done] Elapsed: {(time.time()-t0)/60:.2f} min")

if __name__ == "__main__":
    main()
