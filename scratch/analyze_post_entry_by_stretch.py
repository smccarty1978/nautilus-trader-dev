import os, sys, time
from pathlib import Path
import numpy as np
import pandas as pd

PROJECT_ROOT = Path("c:/Users/Scott McCarty/Projects/Nautilus Trader")
sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)

def analyze_feature_post_entry(df, feat_col):
    print(f"\n==============================================================")
    print(f"STRETCH FEATURE: {feat_col}")
    print(f"==============================================================")
    
    sub = df[[feat_col, "mfe_before_flip", "mae_before_flip", "pnl_60s_atr", "time_to_0p5_atr"]].copy()
    sub[feat_col] = pd.to_numeric(sub[feat_col], errors="coerce")
    sub = sub.dropna(subset=[feat_col, "mfe_before_flip"])
    
    # Calculate 20th and 80th percentiles
    p20 = sub[feat_col].quantile(0.20)
    p80 = sub[feat_col].quantile(0.80)
    
    low_cohort = sub[sub[feat_col] <= p20].copy()
    high_cohort = sub[sub[feat_col] >= p80].copy()
    
    print(f"Full Sample Clean Count: {len(sub):,}")
    print(f"20th Percentile: {p20:.4f} (Count in Lowest 20% Cohort: {len(low_cohort):,})")
    print(f"80th Percentile: {p80:.4f} (Count in Highest 20% Cohort: {len(high_cohort):,})")
    
    cohorts = {
        "Lowest 20% Stretch": low_cohort,
        "Highest 20% Stretch": high_cohort
    }
    
    # 1. Base Probability of reaching 2.0 ATR
    print("\n--- 1. Base Target Probabilities ---")
    for name, Coh in cohorts.items():
        base_p = (Coh["mfe_before_flip"] >= 2.0).mean() * 100
        p05_p = (Coh["mfe_before_flip"] >= 0.5).mean() * 100
        print(f"  {name:<25}: P(MFE >= 0.5 ATR) = {p05_p:.2f}%, P(MFE >= 2.0 ATR) = {base_p:.2f}%")
        
    # 2. Probability of reaching 2 ATR after reaching 0.5 ATR
    print("\n--- 2. Conditional Probability: P(MFE >= 2.0 | MFE >= 0.5) ---")
    for name, Coh in cohorts.items():
        reached_05 = Coh[Coh["mfe_before_flip"] >= 0.5]
        cond_p = (reached_05["mfe_before_flip"] >= 2.0).mean() * 100
        print(f"  {name:<25}: P(MFE >= 2.0 | MFE >= 0.5) = {cond_p:.2f}% ({len(reached_05):,} trades reached 0.5 ATR)")

    # 3. Time-to-0.5 ATR distributions (for trades that hit 0.5 ATR)
    print("\n--- 3. Time to +0.5 ATR Distribution (For Trades Reaching 0.5 ATR) ---")
    for name, Coh in cohorts.items():
        reached_05 = Coh[Coh["mfe_before_flip"] >= 0.5].copy()
        times = reached_05["time_to_0p5_atr"].dropna().to_numpy()
        
        if len(times) == 0:
            print(f"  {name:<25}: No trades reached 0.5 ATR with valid time data.")
            continue
            
        med = np.median(times)
        mean_t = np.mean(times)
        p25 = np.percentile(times, 25)
        p75 = np.percentile(times, 75)
        
        # Binned speed
        pct_15s = np.mean(times <= 15.0) * 100
        pct_30s = np.mean(times <= 30.0) * 100
        pct_60s = np.mean(times <= 60.0) * 100
        pct_slow = np.mean(times > 30.0) * 100
        
        print(f"  {name:<25}:")
        print(f"    Touch Count    : {len(times)}")
        print(f"    Median / Mean  : {med:.1f}s / {mean_t:.1f}s")
        print(f"    IQR (25% - 75%): {p25:.1f}s - {p75:.1f}s")
        print(f"    Speed Buckets  : <=15s: {pct_15s:.1f}%, <=30s: {pct_30s:.1f}%, <=60s: {pct_60s:.1f}%, >30s: {pct_slow:.1f}%")

    # 4. 60-second PnL gate performance
    print("\n--- 4. 60-Second PnL Gate Performance ---")
    # Let's test different thresholds: PnL at 60s >= +0.0 ATR, >= +0.20 ATR, >= +0.30 ATR
    thresholds = [0.0, 0.20, 0.30]
    
    for name, Coh in cohorts.items():
        print(f"  Cohort: {name}")
        base_p = (Coh["mfe_before_flip"] >= 2.0).mean() * 100
        
        for theta in thresholds:
            gate_pass = Coh[Coh["pnl_60s_atr"] >= theta]
            gate_fail = Coh[Coh["pnl_60s_atr"] < theta]
            
            pass_wr = (gate_pass["mfe_before_flip"] >= 2.0).mean() * 100 if len(gate_pass) > 0 else 0.0
            fail_wr = (gate_fail["mfe_before_flip"] >= 2.0).mean() * 100 if len(gate_fail) > 0 else 0.0
            
            pass_ratio = len(gate_pass) / len(Coh) * 100
            
            # Improvement over baseline
            lift = pass_wr - base_p
            
            print(f"    Gate: PnL_60s >= {theta:+.2f} ATR (Pass rate: {pass_ratio:.1f}%)")
            print(f"      Pass (n={len(gate_pass):<5}): P(MFE >= 2.0) = {pass_wr:.2f}% (Lift: {lift:+.2f}%)")
            print(f"      Fail (n={len(gate_fail):<5}): P(MFE >= 2.0) = {fail_wr:.2f}%")

def main():
    ds_path = "scratch/bar1_conditioning_dataset.parquet"
    if not os.path.exists(ds_path):
        print(f"Error: {ds_path} not found.")
        return
        
    df = pd.read_parquet(ds_path)
    
    # VWAP signed features
    df["vwap_z_signed"] = ((df["entry_px_bar1"] - df["vwap"]) / df["entry_atr"].replace(0, 1.0)) * df["signal_direction"]
    
    # Filter for out of sample or full sample?
    # The user says "using the same Bar1-confirmed population" - wait, in the post-entry evolution study,
    # did we evaluate Full Sample or OOS?
    # In predict_bar1_excursions.py, it scanned all years (2020-2026), and printed results on the full sample.
    # In analyze_post_entry_evolution.py, it filtered for OOS years (2023-2026) and kmeans_static_aligned == 0.
    # But wait, the user's prompt says: "Using the same Bar1-confirmed population, evaluate conditional continuation probabilities..."
    # And the conditional continuation probabilities study evaluated cohorts for both Full Sample and individual years (2023-2026).
    # Let's run this post-entry stretch study on the Full Sample (2020-2026) to maximize sample size and statistical power,
    # but let's also break it down for OOS years (2023-2026) if needed.
    # Let's run it on the Full Sample first as the primary cohort.
    
    features = ["dist_ema3_atr", "dist_ema13_atr", "vwap_z_signed"]
    for feat in features:
        analyze_feature_post_entry(df, feat)

if __name__ == "__main__":
    main()
