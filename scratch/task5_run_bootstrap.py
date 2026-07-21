"""Task 5 & 6: Optimized Monthly Block Bootstrap Significance Re-Validation."""
import pandas as pd
import numpy as np
from pathlib import Path
import warnings

# Suppress pandas to_period timezone warnings
warnings.filterwarnings("ignore", category=UserWarning)

PROJECT_ROOT = Path("c:/Users/Scott McCarty/Projects/Nautilus Trader")
RESULTS_DIR = PROJECT_ROOT / "backtests/hmm_state_filtered/results"
OOS_YEARS = [2023, 2024, 2025, 2026]
NQ_MULT = 20.0
COMM_PER_CTR_RT = 5.0
B_ITER = 10000
SEED = 42

def load_and_deduplicate(prefix: str):
    all_trades = []
    for y in OOS_YEARS:
        folder = RESULTS_DIR / f"{prefix}_{y}"
        p = folder / "trades.parquet"
        if not p.exists():
            continue
        df = pd.read_parquet(p)
        df["pnl"] = (df["exit_px"] - df["entry_px"]) * df["signal_direction"] * NQ_MULT - COMM_PER_CTR_RT
        df["year"] = y
        df["date"] = pd.to_datetime(df["entry_ts"], unit="ns", utc=True).dt.tz_convert("America/New_York")
        df["month"] = df["date"].dt.to_period("M")
        all_trades.append(df)
        
    df_all = pd.concat(all_trades).reset_index(drop=True)
    
    # Check duplicate entry_ts
    entry_counts = df_all.groupby("entry_ts").size()
    is_duplicate = entry_counts.max() > 1
    
    # Deduplicate:
    # Collapse to one row per trade-event by summing the contracts (c1/c2 dual contracts)
    if is_duplicate:
        dedup = df_all.groupby("entry_ts").agg({
            "pnl": "sum",
            "entry_atr": "first",
            "year": "first",
            "month": "first",
            "signal_direction": "first"
        }).reset_index()
    else:
        dedup = df_all.copy()
        
    return dedup

def run_bootstrap_pooled(df, n_months):
    np.random.seed(SEED)
    unique_months = df["month"].unique()
    
    # Pre-extract arrays to avoid slow pandas slicing inside loop
    month_dict = {m: group["pnl"].values for m, group in df.groupby("month")}
    
    boot_means = []
    boot_annual_pnl = []
    
    for _ in range(B_ITER):
        # Step 3: Resample blocks with replacement
        resampled_months = np.random.choice(unique_months, size=n_months, replace=True)
        pnl_sum = 0
        pnl_count = 0
        for m in resampled_months:
            arr = month_dict[m]
            pnl_sum += arr.sum()
            pnl_count += len(arr)
        boot_means.append(pnl_sum / pnl_count if pnl_count > 0 else 0.0)
        
        # Step 4: Annualized Expected PnL (Resample 12 months)
        resampled_annual = np.random.choice(unique_months, size=12, replace=True)
        annual_sum = sum(month_dict[m].sum() for m in resampled_annual)
        boot_annual_pnl.append(annual_sum)
        
    boot_means = np.array(boot_means)
    boot_annual_pnl = np.array(boot_annual_pnl)
    
    return {
        "boot_mean": boot_means.mean(),
        "se": boot_means.std(),
        "5th": np.percentile(boot_means, 5),
        "95th": np.percentile(boot_means, 95),
        "p_le_0": (boot_means <= 0).mean(),
        "annual_pnl_mean": boot_annual_pnl.mean(),
        "p_annual_le_0": (boot_annual_pnl <= 0).mean()
    }

def run_bootstrap_per_year(df, year):
    np.random.seed(SEED)
    df_y = df[df["year"] == year]
    unique_months = df_y["month"].unique()
    n_months_y = len(unique_months)
    
    if n_months_y == 0:
        return {"obs": 0.0, "boot_mean": 0.0, "5th": 0.0, "95th": 0.0, "p_le_0": 0.0, "n_months": 0}
        
    month_dict = {m: group["pnl"].values for m, group in df_y.groupby("month")}
    
    boot_means = []
    for _ in range(B_ITER):
        resampled_months = np.random.choice(unique_months, size=n_months_y, replace=True)
        pnl_sum = 0
        pnl_count = 0
        for m in resampled_months:
            arr = month_dict[m]
            pnl_sum += arr.sum()
            pnl_count += len(arr)
        boot_means.append(pnl_sum / pnl_count if pnl_count > 0 else 0.0)
        
    boot_means = np.array(boot_means)
    obs_mean = df_y["pnl"].mean()
    
    return {
        "obs": obs_mean,
        "boot_mean": boot_means.mean(),
        "5th": np.percentile(boot_means, 5),
        "95th": np.percentile(boot_means, 95),
        "p_le_0": (boot_means <= 0).mean(),
        "n_months": n_months_y
    }

def run_bootstrap_direction_2024(df, direction):
    np.random.seed(SEED)
    df_y = df[(df["year"] == 2024) & (df["signal_direction"] == direction)]
    unique_months = df[df["year"] == 2024]["month"].unique()
    n_months_y = len(unique_months)
    
    month_dict = {m: group["pnl"].values for m, group in df_y.groupby("month")}
    for m in unique_months:
        if m not in month_dict:
            month_dict[m] = np.array([])
            
    boot_means = []
    for _ in range(B_ITER):
        resampled_months = np.random.choice(unique_months, size=n_months_y, replace=True)
        pnl_sum = 0
        pnl_count = 0
        for m in resampled_months:
            arr = month_dict[m]
            pnl_sum += arr.sum()
            pnl_count += len(arr)
        boot_means.append(pnl_sum / pnl_count if pnl_count > 0 else 0.0)
        
    boot_means = np.array(boot_means)
    obs_mean = df_y["pnl"].mean() if len(df_y) > 0 else 0.0
    
    return {
        "obs": obs_mean,
        "boot_mean": boot_means.mean(),
        "p_le_0": (boot_means <= 0).mean()
    }

def run_bootstrap_vol_gate_2024(df):
    np.random.seed(SEED)
    df_y = df[(df["year"] == 2024) & (df["entry_atr"] < 15.0)]
    unique_months = df[df["year"] == 2024]["month"].unique()
    n_months_y = len(unique_months)
    
    month_dict = {m: group["pnl"].values for m, group in df_y.groupby("month")}
    for m in unique_months:
        if m not in month_dict:
            month_dict[m] = np.array([])
            
    boot_means = []
    for _ in range(B_ITER):
        resampled_months = np.random.choice(unique_months, size=n_months_y, replace=True)
        pnl_sum = 0
        pnl_count = 0
        for m in resampled_months:
            arr = month_dict[m]
            pnl_sum += arr.sum()
            pnl_count += len(arr)
        boot_means.append(pnl_sum / pnl_count if pnl_count > 0 else 0.0)
        
    boot_means = np.array(boot_means)
    obs_mean = df_y["pnl"].mean() if len(df_y) > 0 else 0.0
    
    return {
        "obs": obs_mean,
        "boot_mean": boot_means.mean(),
        "p_le_0": (boot_means <= 0).mean()
    }

def analyze_cohort(prefix: str, name: str):
    dedup = load_and_deduplicate(prefix)
    
    dedup_n = len(dedup)
    pnl_std = dedup["pnl"].std()
    unique_months = dedup["month"].unique()
    n_months = len(unique_months)
    
    # Step 2: Naive monthly t-stat
    monthly_pnl = dedup.groupby("month")["pnl"].sum()
    naive_t = monthly_pnl.mean() / (monthly_pnl.std() / np.sqrt(n_months))
    
    # Step 3 & 4: Pooled bootstrap
    pooled_boot = run_bootstrap_pooled(dedup, n_months)
    
    # Step 5: Per-year bootstrap
    yearly_results = []
    for y in OOS_YEARS:
        y_boot = run_bootstrap_per_year(dedup, y)
        yearly_results.append((y, y_boot))
        
    # Step 6: 2024 Long/Short split
    long_2024 = run_bootstrap_direction_2024(dedup, 1)
    short_2024 = run_bootstrap_direction_2024(dedup, -1)
    
    # Step 7 Check: 2024 ATR < 15 bootstrap (only valid for Bar 1 cohort)
    vol_2024 = None
    if "minatr15p0" not in prefix:
        vol_2024 = run_bootstrap_vol_gate_2024(dedup)
        
    return {
        "prefix": prefix,
        "name": name,
        "dedup_n": dedup_n,
        "pnl_std": pnl_std,
        "n_months": n_months,
        "naive_t": naive_t,
        "pooled_boot": pooled_boot,
        "yearly": yearly_results,
        "long_2024": long_2024,
        "short_2024": short_2024,
        "vol_2024": vol_2024
    }

def main():
    print("Running optimized significance re-validation sweeps for both cohorts...")
    
    # Cohort 1: Bar-1 Confirmed
    bar1_res = analyze_cohort("nq_hmm_4_s3_pt2p0", "Bar-1 Confirmed")
    
    # Cohort 2: Raw Flips (vol > 15)
    flip_res = analyze_cohort("nq_hmm_4_s3_pt2p0_ancflip_flip_p4_minatr15p0", "Raw Flips (vol > 15)")
    
    # Output Schema Printout
    print("\n\n" + "="*80)
    print("  FINAL SIGNIFICANCE SUMMARY TABLES")
    print("="*80)
    
    print("\n--- POOLED OOS METRICS TABLE ---")
    print(f"{'Cohort':<22} | {'Dedup N':<7} | {'Per-Tr sigma':<12} | {'Months':<6} | {'Naive t':<7} | {'Boot Mean +/- SE':<17} | {'5th / 95th Pct':<16} | {'P(<=0)':<7} | {'Ann Expected PnL':<16} | {'P(Ann<=0)':<9}")
    print("-" * 143)
    for res in [bar1_res, flip_res]:
        pb = res["pooled_boot"]
        print(f"{res['name']:<22} | {res['dedup_n']:<7} | ${res['pnl_std']:>10.2f} | {res['n_months']:<6} | {res['naive_t']:>7.4f} | ${pb['boot_mean']:>6.2f} +/- ${pb['se']:>5.2f} | ${pb['5th']:>6.2f} / ${pb['95th']:>6.2f} | {pb['p_le_0']:>6.1%} | ${pb['annual_pnl_mean']:>14,.2f} | {pb['p_annual_le_0']:>8.1%}")
        
    print("\n--- PER-YEAR METRICS TABLE ---")
    print(f"{'Cohort':<22} | {'Year':<4} | {'Obs $/tr':<9} | {'Boot Mean':<9} | {'Boot 5th':<9} | {'Boot 95th':<9} | {'P(<=0)':<6} | {'Months':<6}")
    print("-" * 96)
    for res in [bar1_res, flip_res]:
        for y, yb in res["yearly"]:
            print(f"{res['name']:<22} | {y:<4} | ${yb['obs']:>8.2f} | ${yb['boot_mean']:>8.2f} | ${yb['5th']:>8.2f} | ${yb['95th']:>8.2f} | {yb['p_le_0']:>5.1%} | {yb['n_months']:<6}")

    print("\n--- 2024 DIRECTIONAL & VOL GATES SIGN-LEVEL ---")
    print(f"  Bar-1 2024 Long-Only:  Obs=${bar1_res['long_2024']['obs']:.2f} | BootMean=${bar1_res['long_2024']['boot_mean']:.2f} | P(<=0)={bar1_res['long_2024']['p_le_0']:.2%}")
    print(f"  Bar-1 2024 Short-Only: Obs=${bar1_res['short_2024']['obs']:.2f} | BootMean=${bar1_res['short_2024']['boot_mean']:.2f} | P(<=0)={bar1_res['short_2024']['p_le_0']:.2%}")
    if bar1_res['vol_2024'] is not None:
        print(f"  Bar-1 2024 ATR < 15:   Obs=${bar1_res['vol_2024']['obs']:.2f} | BootMean=${bar1_res['vol_2024']['boot_mean']:.2f} | P(<=0)={bar1_res['vol_2024']['p_le_0']:.2%}")

    print(f"\n  Raw-Flip 2024 Long-Only:  Obs=${flip_res['long_2024']['obs']:.2f} | BootMean=${flip_res['long_2024']['boot_mean']:.2f} | P(<=0)={flip_res['long_2024']['p_le_0']:.2%}")
    print(f"  Raw-Flip 2024 Short-Only: Obs=${flip_res['short_2024']['obs']:.2f} | BootMean=${flip_res['short_2024']['boot_mean']:.2f} | P(<=0)={flip_res['short_2024']['p_le_0']:.2%}")

if __name__ == "__main__":
    main()
