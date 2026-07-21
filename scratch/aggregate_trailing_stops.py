import os, sys
from pathlib import Path
import numpy as np
import pandas as pd

PROJECT_ROOT = Path("c:/Users/Scott McCarty/Projects/Nautilus Trader")
sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

YEARS = [2021, 2022, 2023, 2024]

def load_all_years(suffix):
    dfs = []
    for y in YEARS:
        p = PROJECT_ROOT / f"backtests/baseline_flip_parity/results/nq_live_{y}{suffix}/trades.parquet"
        if not p.exists():
            print(f"File not found: {p}")
            continue
        df = pd.read_parquet(p)
        df["year"] = y
        dfs.append(df)
    if not dfs:
        return pd.DataFrame()
    return pd.concat(dfs, ignore_index=True)

def print_summary(df, name):
    n = len(df)
    if n == 0:
        print(f"\nNo trades found for {name}")
        return
    
    # Calculate PnL stats
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
    
    print("\n" + "="*80)
    print(f"  SUMMARY FOR: {name}")
    print("="*80)
    print(f"  Total Trades:         {n:,}")
    print(f"  Win Rate:             {win_rate:.2f}%")
    print(f"  Mean PnL (ATR):       {mean_atr:.4f}")
    print(f"  Mean PnL (Points):    {mean_pts:.2f} pts (${mean_pts*20.0:.2f})")
    print(f"  Gross Profit Factor:  {gross_pf:.2f}")
    print(f"  Net Profit Factor:    {net_pf:.2f}")
    print(f"  Total Net PnL ($):    ${df['net_pnl_usd'].sum():,.2f}")
    
    if "exit_reason" in df.columns:
        print("\n  Exit Reasons Breakdown:")
        counts = df["exit_reason"].value_counts()
        for r, cnt in counts.items():
            print(f"    {r:<15}: {cnt:>5} ({cnt/n:.1%})")
            
    # Long vs Short
    print("\n  Directional Breakdown:")
    df_long = df[df["signal_direction"] == 1]
    df_short = df[df["signal_direction"] == -1]
    for side_name, df_sub in [("Longs", df_long), ("Shorts", df_short)]:
        sub_n = len(df_sub)
        if sub_n == 0: continue
        sub_win = (df_sub["exit_pnl_pts"] > 0).mean() * 100
        sub_mean_atr = df_sub["exit_pnl_atr"].mean()
        sub_g_wins = df_sub[df_sub["gross_pnl_usd"] > 0]["gross_pnl_usd"].sum()
        sub_g_losses = abs(df_sub[df_sub["gross_pnl_usd"] < 0]["gross_pnl_usd"].sum())
        sub_pf = sub_g_wins / sub_g_losses if sub_g_losses > 0 else float("inf")
        print(f"    {side_name:<7}: Trades={sub_n:>5,}, WinRate={sub_win:>5.1f}%, MeanATR={sub_mean_atr:>7.4f}, GrossPF={sub_pf:>5.2f}")

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
    df_base = load_all_years("_base")
    df_trail = load_all_years("_trail_tp1.5_sl1.0")
    
    print_summary(df_base, "BASELINE PARITY (TP=1.0, SL=1.0)")
    print_summary(df_trail, "TRAILING STOP (TP=1.5, SL=1.0, BE=0.25, Trail=0.25)")
    
    # Calculate comparative lift
    if len(df_base) > 0 and len(df_trail) > 0:
        base_mean = df_base["exit_pnl_atr"].mean()
        trail_mean = df_trail["exit_pnl_atr"].mean()
        lift = trail_mean - base_mean
        print("\n" + "="*80)
        print("  COMPARATIVE PERFORMANCE LIFT")
        print("="*80)
        print(f"  Baseline Mean PnL (ATR):     {base_mean:.4f}")
        print(f"  Trailing Stop Mean PnL (ATR):{trail_mean:.4f}")
        print(f"  Excursion Lift (ATR):        {lift:+.4f}")
        
        # Compare year-by-year lift
        print("\n  Year-by-Year Mean PnL (ATR) comparison:")
        for yr in YEARS:
            base_yr = df_base[df_base["year"] == yr]
            trail_yr = df_trail[df_trail["year"] == yr]
            if len(base_yr) > 0 and len(trail_yr) > 0:
                bm = base_yr["exit_pnl_atr"].mean()
                sm = trail_yr["exit_pnl_atr"].mean()
                print(f"    {yr}: Baseline={bm:>7.4f} | Trail={sm:>7.4f} | Lift={sm-bm:>+7.4f}")

if __name__ == "__main__":
    main()
