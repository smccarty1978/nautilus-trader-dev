"""Load and analyze ablation results vs. baseline."""
import pandas as pd
import numpy as np
from pathlib import Path

PROJECT_ROOT = Path("c:/Users/Scott McCarty/Projects/Nautilus Trader")
RESULTS_DIR = PROJECT_ROOT / "backtests/hmm_state_filtered/results"
OOS_YEARS = [2023, 2024, 2025, 2026]
NQ_MULT = 20.0
COMM_PER_CTR_RT = 5.0

def analyze_sweep(prefix: str):
    all_trades = []
    yearly = {}
    
    for y in OOS_YEARS:
        folder = RESULTS_DIR / f"{prefix}_{y}"
        p = folder / "trades.parquet"
        if not p.exists():
            continue
            
        df = pd.read_parquet(p)
        df["year"] = y
        df["pnl"] = (df["exit_px"] - df["entry_px"]) * df["signal_direction"] * NQ_MULT - COMM_PER_CTR_RT
        all_trades.append(df)
        
        n_records = len(df)
        net_pnl = df["pnl"].sum()
        win_rate = (df["pnl"] > 0).mean()
        avg_pnl = df["pnl"].mean()
        
        yearly[y] = {
            "records": n_records,
            "win_rate": win_rate,
            "net_pnl": net_pnl,
            "avg_pnl": avg_pnl
        }
        
    if not all_trades:
        return None, None
        
    oos_df = pd.concat(all_trades)
    pooled = {
        "records": len(oos_df),
        "win_rate": (oos_df["pnl"] > 0).mean(),
        "net_pnl": oos_df["pnl"].sum(),
        "avg_pnl": oos_df["pnl"].mean()
    }
    return yearly, pooled

def main():
    print("ANALYZING PRODUCTION (A) vs. ABLATION (B)...")
    
    # 1. Analyze Production Baseline (hmm_4 state 3)
    prod_y, prod_p = analyze_sweep("nq_hmm_4_s3_pt2p0")
    
    # 2. Analyze Ablation (no state filter)
    # We check if 'nq_hmm_4_s-1_pt2p0_noStFilter' or 'nq_hmm_4_s-1_pt2p0_ablation' is available
    ab_y, ab_p = analyze_sweep("nq_hmm_4_s-1_pt2p0_noStFilter")
    if ab_y is None:
        ab_y, ab_p = analyze_sweep("nq_hmm_4_s-1_pt2p0_ablation")
        
    if prod_p is None or ab_p is None:
        print("Error: Could not load one of the sweeps.")
        return
        
    print("\n--- SIDE-BY-SIDE COMPARISON TABLE ---")
    print(f"{'Year':<5} | {'Prod Records':<12} | {'Prod WR':<8} | {'Prod $/tr':<10} | {'Prod Net PnL':<13} | {'Ab Records':<10} | {'Ab WR':<7} | {'Ab $/tr':<8} | {'Ab Net PnL':<11}")
    print("-" * 105)
    
    for y in OOS_YEARS:
        py = prod_y[y]
        ay = ab_y[y]
        print(f"{y:<5} | {py['records']:<12} | {py['win_rate']:>7.1%} | ${py['avg_pnl']:>8.2f} | ${py['net_pnl']:>+11.2f} | {ay['records']:<10} | {ay['win_rate']:>6.1%} | ${ay['avg_pnl']:>6.2f} | ${ay['net_pnl']:>+9.2f}")
        
    print("-" * 105)
    print(f"{'OOS':<5} | {prod_p['records']:<12} | {prod_p['win_rate']:>7.1%} | ${prod_p['avg_pnl']:>8.2f} | ${prod_p['net_pnl']:>+11.2f} | {ab_p['records']:<10} | {ab_p['win_rate']:>6.1%} | ${ab_p['avg_pnl']:>6.2f} | ${ab_p['net_pnl']:>+9.2f}")

if __name__ == "__main__":
    main()
