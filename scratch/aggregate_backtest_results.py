"""Aggregate Nautilus Trader backtest results and verify parity with offline simulation"""
from __future__ import annotations
import os, sys
from pathlib import Path
import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
project_root = Path(__file__).parent.parent
os.chdir(project_root)

# Base path for results
BASE = Path("backtests/hmm_state_filtered/results")
DIR_PREFIX = "nq_kmeans_4_s0_pt0p5_sl2p0_ancflip_be0p25_lvlm0p25_minatr15p0"
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
    # entry_px, exit_px are actual filled prices.
    # exit_reason is 'PT', 'stop_loss', 'BE_stop', 'regime_flip', 'max_hold'
    df_trades["pnl_points"] = (df_trades["exit_px"] - df_trades["entry_px"]) * df_trades["signal_direction"]
    df_trades["gross_pnl"] = df_trades["pnl_points"] * 20.0
    
    # Apply strict $10 transaction friction per trade
    df_trades["net_pnl"] = df_trades["gross_pnl"] - 10.0
    
    print("\n" + "="*100)
    # Clean up name: nq_kmeans_4_s0_pt0p5_sl2p0_ancflip_be0p25_lvlm0p25_minatr15p0
    print("  NAUTILUS TRADER BACKTEST VERIFICATION: PT 0.5 / SL 2.0 / BE +0.25 / BE -0.25 / MIN_ATR 15.0")
    print("="*100)
    print(f"  {'Year':<6} {'Trades':>6} | {'Win%':>6} {'Loss% (SL)':>10} {'BE Stop%':>10} {'Regime Exit%':>12} | {'Net PnL ($)':>12} {'PF':>6}")
    print("  " + "-"*96)
    
    for y in YEARS:
        df_y = df_trades[df_trades["year"] == y].copy()
        n = len(df_y)
        if n == 0:
            print(f"  {y:<6} {'0':>6} | {'0.0%':>6} {'0.0%':>10} {'0.0%':>10} {'0.0%':>12} | {'$0.00':>12} {'N/A':>6}")
            continue
            
        win_rate = (df_y["exit_reason"] == "PT").mean() * 100
        sl_rate = (df_y["exit_reason"] == "stop_loss").mean() * 100
        be_rate = (df_y["exit_reason"] == "BE_stop").mean() * 100
        regime_rate = (df_y["exit_reason"] == "regime_flip").mean() * 100
        
        tot_net = df_y["net_pnl"].sum()
        wins = df_y[df_y["net_pnl"] > 0]["net_pnl"].sum()
        losses = df_y[df_y["net_pnl"] < 0]["net_pnl"].sum()
        pf = wins / abs(losses) if losses != 0 else np.nan
        
        print(f"  {y:<6} {n:>6,} | {win_rate:>5.1f}% {sl_rate:>9.1f}% {be_rate:>9.1f}% {regime_rate:>11.1f}% | {tot_net:>+11.2f}$ {pf:>6.2f}")
        
    # Aggregate OOS stats
    n_tot = len(df_trades)
    win_rate = (df_trades["exit_reason"] == "PT").mean() * 100
    sl_rate = (df_trades["exit_reason"] == "stop_loss").mean() * 100
    be_rate = (df_trades["exit_reason"] == "BE_stop").mean() * 100
    regime_rate = (df_trades["exit_reason"] == "regime_flip").mean() * 100
    
    tot_net = df_trades["net_pnl"].sum()
    wins = df_trades[df_trades["net_pnl"] > 0]["net_pnl"].sum()
    losses = df_trades[df_trades["net_pnl"] < 0]["net_pnl"].sum()
    pf = wins / abs(losses) if losses != 0 else np.nan
    
    print("  " + "-"*96)
    print(f"  {'Total':<6} {n_tot:>6,} | {win_rate:>5.1f}% {sl_rate:>9.1f}% {be_rate:>9.1f}% {regime_rate:>11.1f}% | {tot_net:>+11.2f}$ {pf:>6.2f}")
    print("="*100)


if __name__ == "__main__":
    main()
