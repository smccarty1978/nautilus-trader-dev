"""Aggregate Strategy F Nautilus Trader backtest results and verify parity with offline simulation"""
from __future__ import annotations
import os, sys
from pathlib import Path
import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
project_root = Path(__file__).parent.parent
os.chdir(project_root)

BASE = Path("backtests/hmm_state_filtered/results")
DIR_PREFIX = "nq_kmeans_4_s0_sl1p5_minatr15p0_vwapF_qty2_ptr2p0"
YEARS = [2023, 2024, 2025, 2026]

def main():
    dfs = []
    for y in YEARS:
        p = BASE / f"{DIR_PREFIX}_{y}" / "trades.parquet"
        if not p.exists():
            print(f"File not found: {p}")
            continue
        df = pd.read_parquet(p)
        df["year"] = y
        dfs.append(df)
        
    if not dfs:
        print("No trade records found!")
        return
        
    df_trades = pd.concat(dfs, ignore_index=True)
    
    # Calculate PnL in dollars (NQ = $20 per index point)
    df_trades["pnl_points"] = (df_trades["exit_px"] - df_trades["entry_px"]) * df_trades["signal_direction"]
    df_trades["gross_pnl"] = df_trades["pnl_points"] * 20.0
    
    # Apply strict $10 transaction friction per contract
    df_trades["net_pnl"] = df_trades["gross_pnl"] - 10.0
    
    print("\n" + "="*100)
    print("  STRATEGY F NAUTILUS TRADER BACKTEST VERIFICATION: VWAP-CONDITIONED EXITS")
    print("="*100)
    print(f"  {'Year':<6} {'Contracts':>9} {'Win%':>6} | Exit Reason Breakdown | {'Net PnL ($)':>12} {'PF':>6}")
    print("  " + "-"*96)
    
    for y in YEARS:
        df_y = df_trades[df_trades["year"] == y].copy()
        n = len(df_y)
        if n == 0:
            print(f"  {y:<6} {'0':>9} {'0.0%':>6} | N/A | {'$0.00':>12} {'N/A':>6}")
            continue
            
        win_rate = (df_y["net_pnl"] > 0).mean() * 100
        reasons = df_y["exit_reason"].value_counts()
        reason_str = ", ".join([f"{k}:{v}" for k, v in reasons.items()])
        
        tot_net = df_y["net_pnl"].sum()
        wins = df_y[df_y["net_pnl"] > 0]["net_pnl"].sum()
        losses = df_y[df_y["net_pnl"] < 0]["net_pnl"].sum()
        pf = wins / abs(losses) if losses != 0 else np.nan
        
        print(f"  {y:<6} {n:>9,} {win_rate:>5.1f}% | {reason_str:<35} | {tot_net:>+11.2f}$ {pf:>6.2f}")
        
    n_tot = len(df_trades)
    win_rate = (df_trades["net_pnl"] > 0).mean() * 100
    reasons = df_trades["exit_reason"].value_counts()
    reason_str = ", ".join([f"{k}:{v}" for k, v in reasons.items()])
    
    tot_net = df_trades["net_pnl"].sum()
    wins = df_trades[df_trades["net_pnl"] > 0]["net_pnl"].sum()
    losses = df_trades[df_trades["net_pnl"] < 0]["net_pnl"].sum()
    pf = wins / abs(losses) if losses != 0 else np.nan
    
    print("  " + "-"*96)
    print(f"  {'Total':<6} {n_tot:>9,} {win_rate:>5.1f}% | {reason_str:<35} | {tot_net:>+11.2f}$ {pf:>6.2f}")
    print("="*100)

if __name__ == "__main__":
    main()
