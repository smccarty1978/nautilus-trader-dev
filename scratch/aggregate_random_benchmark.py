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

def get_yearly_stats(df):
    stats_map = {}
    for yr in YEARS:
        grp = df[df["year"] == yr]
        n = len(grp)
        if n == 0:
            stats_map[yr] = {"n": 0, "win_rate": 0.0, "mean_atr": 0.0, "gross_pf": 0.0, "net_pf": 0.0, "total_net_pnl": 0.0}
            continue
        grp = grp.copy()
        grp["gross_pnl_usd"] = grp["exit_pnl_pts"] * 20.0
        grp["net_pnl_usd"] = grp["gross_pnl_usd"] - 10.0
        
        y_win = (grp["exit_pnl_pts"] > 0).mean() * 100
        y_mean_atr = grp["exit_pnl_atr"].mean()
        
        y_g_wins = grp[grp["gross_pnl_usd"] > 0]["gross_pnl_usd"].sum()
        y_g_losses = abs(grp[grp["gross_pnl_usd"] < 0]["gross_pnl_usd"].sum())
        y_g_pf = y_g_wins / y_g_losses if y_g_losses > 0 else float("inf")
        
        y_n_wins = grp[grp["net_pnl_usd"] > 0]["net_pnl_usd"].sum()
        y_n_losses = abs(grp[grp["net_pnl_usd"] < 0]["net_pnl_usd"].sum())
        y_n_pf = y_n_wins / y_n_losses if y_n_losses > 0 else float("inf")
        
        y_net_pnl = grp["net_pnl_usd"].sum()
        stats_map[yr] = {
            "n": n,
            "win_rate": y_win,
            "mean_atr": y_mean_atr,
            "gross_pf": y_g_pf,
            "net_pf": y_n_pf,
            "total_net_pnl": y_net_pnl
        }
    return stats_map

def main():
    print("Loading backtest results...")
    
    cand_suffix = "_stall_sma13_s3_g0_long"
    rand_suffix = "_random_long"
    
    cand_raw = load_all_years(cand_suffix)
    rand_raw = load_all_years(rand_suffix)
    
    if len(cand_raw) == 0:
        print(f"Error: No trades loaded for Candidate 1 ({cand_suffix})")
        return
    if len(rand_raw) == 0:
        print(f"Error: No trades loaded for Random Long ({rand_suffix})")
        return
        
    s_c1 = get_stats(cand_raw)
    s_rand = get_stats(rand_raw)
    
    print("\n" + "="*80)
    print("  RANDOM LONG ENTRY BENCHMARK REPORT")
    print("="*80)
    print(f"{'Metric':<30} | {'Candidate 1 (Stall-State)':<25} | {'Random Long Entry':<20}")
    print("-"*80)
    print(f"{'Total Trades':<30} | {s_c1['n']:<25,} | {s_rand['n']:<20,}")
    print(f"{'Win Rate (%)':<30} | {s_c1['win_rate']:<25.2f}% | {s_rand['win_rate']:<20.2f}%")
    print(f"{'Mean PnL (ATR)':<30} | {s_c1['mean_atr']:<25.4f} | {s_rand['mean_atr']:<20.4f}")
    print(f"{'Mean PnL (Points)':<30} | {s_c1['mean_pts']:<25.2f} | {s_rand['mean_pts']:<20.2f}")
    print(f"{'Gross Profit Factor':<30} | {s_c1['gross_pf']:<25.2f} | {s_rand['gross_pf']:<20.2f}")
    print(f"{'Net Profit Factor':<30} | {s_c1['net_pf']:<25.2f} | {s_rand['net_pf']:<20.2f}")
    print(f"{'Total Net PnL ($)':<30} | ${s_c1['total_net_pnl']:<24,.2f} | ${s_rand['total_net_pnl']:<19,.2f}")
    print("="*80)
    
    c1_yearly = get_yearly_stats(cand_raw)
    rand_yearly = get_yearly_stats(rand_raw)
    
    print("\n  YEAR-BY-YEAR COMPARATIVE BREAKDOWN")
    print("="*80)
    print(f"{'Year':<5} | {'Stall-State (Trades / Mean ATR / Net PnL)':<40} | {'Random Long (Trades / Mean ATR / Net PnL)':<40}")
    print("-"*80)
    for y in YEARS:
        c1 = c1_yearly[y]
        rd = rand_yearly[y]
        c1_str = f"{c1['n']:,} / {c1['mean_atr']:.4f} ATR / ${c1['total_net_pnl']:+,.2f}"
        rd_str = f"{rd['n']:,} / {rd['mean_atr']:.4f} ATR / ${rd['total_net_pnl']:+,.2f}"
        print(f"{y:<5} | {c1_str:<40} | {rd_str:<40}")
    print("="*80)
    
    # Lift table
    print("\n  PERFORMANCE LIFT ANALYSIS (Candidate 1 vs Random Long)")
    print("="*80)
    print(f"{'Year':<5} | {'Mean ATR Lift':<20} | {'Net PnL Difference ($)':<25}")
    print("-"*80)
    for y in YEARS:
        c1 = c1_yearly[y]
        rd = rand_yearly[y]
        atr_lift = c1['mean_atr'] - rd['mean_atr']
        pnl_diff = c1['total_net_pnl'] - rd['total_net_pnl']
        print(f"{y:<5} | {atr_lift:>+14.4f} ATR | {pnl_diff:>+22,.2f}")
    
    tot_atr_lift = s_c1['mean_atr'] - s_rand['mean_atr']
    tot_pnl_diff = s_c1['total_net_pnl'] - s_rand['total_net_pnl']
    print("-"*80)
    print(f"{'Total':<5} | {tot_atr_lift:>+14.4f} ATR | {tot_pnl_diff:>+22,.2f}")
    print("="*80)

if __name__ == "__main__":
    main()
