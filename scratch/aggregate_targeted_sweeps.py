import os, sys
from pathlib import Path
import numpy as np
import pandas as pd

PROJECT_ROOT = Path("c:/Users/Scott McCarty/Projects/Nautilus Trader")
sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

YEARS = [2020, 2021, 2022, 2023, 2024, 2025, 2026]

def load_all_years(suffix):
    dfs = []
    for y in YEARS:
        p = PROJECT_ROOT / f"backtests/baseline_flip_parity/results/nq_live_{y}{suffix}/trades.parquet"
        if not p.exists():
            continue
        df = pd.read_parquet(p)
        df["year"] = y
        dfs.append(df)
    if not dfs:
        return pd.DataFrame()
    return pd.concat(dfs, ignore_index=True)

def get_stats(df):
    n = len(df)
    if n == 0:
        return None
    
    df["gross_pnl_usd"] = df["exit_pnl_pts"] * 20.0
    df["net_pnl_usd"] = df["gross_pnl_usd"] - 10.0
    
    win_rate = (df["exit_pnl_pts"] > 0).mean() * 100
    mean_atr = df["exit_pnl_atr"].mean()
    mean_pts = df["exit_pnl_pts"].mean()
    
    g_wins = df[df["gross_pnl_usd"] > 0]["gross_pnl_usd"].sum()
    g_losses = abs(df[df["gross_pnl_usd"] < 0]["gross_pnl_usd"].sum())
    gross_pf = g_wins / g_losses if g_losses > 0 else float("inf")
    
    n_wins = df[df["net_pnl_usd"] > 0]["net_pnl_usd"].sum()
    n_losses = abs(df[df["net_pnl_usd"] < 0]["net_pnl_usd"].sum())
    net_pf = n_wins / n_losses if n_losses > 0 else float("inf")
    
    total_net_pnl = df['net_pnl_usd'].sum()
    return {
        "n": n,
        "win_rate": win_rate,
        "mean_atr": mean_atr,
        "mean_pts": mean_pts,
        "gross_pf": gross_pf,
        "net_pf": net_pf,
        "total_net_pnl": total_net_pnl,
        "df": df
    }

def print_summary(stats, name):
    if stats is None:
        print(f"\nNo trades found for {name}")
        return
    
    print("\n" + "="*80)
    print(f"  SUMMARY FOR: {name}")
    print("="*80)
    print(f"  Total Trades:         {stats['n']:,}")
    print(f"  Win Rate:             {stats['win_rate']:.2f}%")
    print(f"  Mean PnL (ATR):       {stats['mean_atr']:.4f}")
    print(f"  Mean PnL (Points):    {stats['mean_pts']:.2f} pts (${stats['mean_pts']*20.0:.2f})")
    print(f"  Gross Profit Factor:  {stats['gross_pf']:.2f}")
    print(f"  Net Profit Factor:    {stats['net_pf']:.2f}")
    print(f"  Total Net PnL ($):    ${stats['total_net_pnl']:,.2f}")
    
    df = stats["df"]
    if "exit_reason" in df.columns:
        print("\n  Exit Reasons Breakdown:")
        counts = df["exit_reason"].value_counts()
        for r, cnt in counts.items():
            print(f"    {r:<15}: {cnt:>5} ({cnt/stats['n']:.1%})")
            
    # Year by Year
    print("\n  Year-by-Year breakdown:")
    for yr, grp in df.groupby("year"):
        y_n = len(grp)
        y_win = (grp["exit_pnl_pts"] > 0).mean() * 100
        y_mean_atr = grp["exit_pnl_atr"].mean()
        y_g_wins = grp[grp["gross_pnl_usd"] > 0]["gross_pnl_usd"].sum()
        y_g_losses = abs(grp[grp["gross_pnl_usd"] < 0]["gross_pnl_usd"].sum())
        y_g_pf = y_g_wins / y_g_losses if y_g_losses > 0 else float("inf")
        y_n_wins = grp[grp["net_pnl_usd"] > 0]["net_pnl_usd"].sum()
        y_n_losses = abs(grp[grp["net_pnl_usd"] < 0]["net_pnl_usd"].sum())
        y_n_pf = y_n_wins / y_n_losses if y_n_losses > 0 else float("inf")
        y_net_pnl = grp["net_pnl_usd"].sum()
        print(f"    {int(yr)}: Trades={y_n:>5,}, WinRate={y_win:>5.1f}%, MeanATR={y_mean_atr:>7.4f}, GrossPF={y_g_pf:>5.2f}, NetPF={y_n_pf:>5.2f}, NetPnL=${y_net_pnl:>+10,.2f}")

def main():
    print("Loading backtest results...")
    
    # Baselines
    s_base = get_stats(load_all_years("_base"))
    s_base_long = get_stats(load_all_years("_base_long"))
    
    # Candidates
    s_c1 = get_stats(load_all_years("_stall_sma13_s3_g0_long"))
    s_c2 = get_stats(load_all_years("_stall_ema21_s4_g0.5_long"))
    s_c3 = get_stats(load_all_years("_stall_sma21_s2_g0"))
    
    print_summary(s_base, "BASELINE BOTH")
    print_summary(s_base_long, "BASELINE LONG-ONLY")
    print_summary(s_c1, "CANDIDATE 1: Long-only SMA13 S3 G0.0")
    print_summary(s_c2, "CANDIDATE 2: Long-only EMA21 S4 G0.5")
    print_summary(s_c3, "CANDIDATE 3: Both SMA21 S2 G0.0")
    
    # Comparative Lifts
    print("\n" + "="*80)
    print("  COMPARATIVE PERFORMANCE LIFTS (ATR)")
    print("="*80)
    
    if s_base_long and s_c1:
        lift_c1 = s_c1["mean_atr"] - s_base_long["mean_atr"]
        print(f"  Candidate 1 vs Baseline Long: {lift_c1:+.4f} ATR  (Net PnL Diff: ${s_c1['total_net_pnl'] - s_base_long['total_net_pnl']:+,.2f})")
        
    if s_base_long and s_c2:
        lift_c2 = s_c2["mean_atr"] - s_base_long["mean_atr"]
        print(f"  Candidate 2 vs Baseline Long: {lift_c2:+.4f} ATR  (Net PnL Diff: ${s_c2['total_net_pnl'] - s_base_long['total_net_pnl']:+,.2f})")
        
    if s_base and s_c3:
        lift_c3 = s_c3["mean_atr"] - s_base["mean_atr"]
        print(f"  Candidate 3 vs Baseline Both: {lift_c3:+.4f} ATR  (Net PnL Diff: ${s_c3['total_net_pnl'] - s_base['total_net_pnl']:+,.2f})")

if __name__ == "__main__":
    main()
