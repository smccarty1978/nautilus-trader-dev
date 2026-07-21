import pandas as pd
import numpy as np
from pathlib import Path

PROJECT_ROOT = Path("c:/Users/Scott McCarty/Projects/Nautilus Trader")
TRADES_FILE = PROJECT_ROOT / "studies" / "keltner_fade" / "results_regime_only" / "trades.parquet"

def run_analysis():
    if not TRADES_FILE.exists():
        print(f"Error: {TRADES_FILE} not found. Run backtest first.")
        return
        
    df = pd.read_parquet(TRADES_FILE)
    
    # Calculate entry ratio:
    # dist_from_basis = (basis_at_entry - fill_price) * direction
    # ratio = dist_from_basis / basis_to_extension_px
    df["dist_from_basis"] = (df["basis_at_entry"] - df["fill_price"]) * df["direction"]
    df["entry_ratio"] = df["dist_from_basis"] / df["basis_to_extension_px"]
    
    print("==================================================")
    # 1. Sweep entry ratio thresholds
    print("ENTRY RATIO PERFORMANCE SWEEP (Regime-Only Exits)")
    print("==================================================")
    print("| Min Ratio | Trades | Win Rate | Profit Factor | Net PnL ($) | Mean MAE (ATR) | Mean Hold (s) |")
    print("| :---: | :---: | :---: | :---: | :---: | :---: | :---: |")
    
    thresholds = [0.5, 0.6, 0.7, 0.8, 0.9, 1.0, 1.1, 1.2, 1.3]
    for thresh in thresholds:
        sub = df[df["entry_ratio"] >= thresh]
        n = len(sub)
        if n == 0:
            print(f"| {thresh:.2f} | 0 | - | - | $0.00 | - | - |")
            continue
            
        wr = (sub["net_pnl"] > 0).mean() * 100
        wins = sub[sub["net_pnl"] > 0]["net_pnl"].sum()
        losses = abs(sub[sub["net_pnl"] < 0]["net_pnl"].sum())
        pf = wins / losses if losses > 0 else float("inf")
        pnl = sub["net_pnl"].sum()
        mean_mae = sub["mae_atr"].mean()
        mean_hold = sub["hold_s"].mean()
        
        print(f"| {thresh:.2f} | {n} | {wr:.1f}% | {pf:.2f} | ${pnl:+,.2f} | {mean_mae:.2f} | {mean_hold:.1f}s |")

    # 2. Joint Gating: Entry Ratio >= 1.0 (entered beyond/at extension) & Slope-Relative
    print("\n==================================================")
    print("SLOPE GATING FOR DEEP ENTRIES (Entry Ratio >= 1.0)")
    print("==================================================")
    deep_df = df[df["entry_ratio"] >= 1.0].copy()
    deep_df["slope_rel"] = deep_df["keltner_slope_atr"] * deep_df["direction"]
    deep_df["slope_bucket"] = np.where(deep_df["slope_rel"] > 0.05, "Trend Continuation (>0.05)",
                                       np.where(deep_df["slope_rel"] < -0.05, "Mean Reverting (<-0.05)", "Flat ([-0.05, 0.05])"))
                                       
    print("| Slope Bucket | Trades | Win Rate | Profit Factor | Net PnL ($) | Mean MAE (ATR) |")
    print("| :--- | :---: | :---: | :---: | :---: | :---: |")
    for sb, grp in deep_df.groupby("slope_bucket"):
        s_wins = grp[grp["net_pnl"] > 0]["net_pnl"].sum()
        s_losses = abs(grp[grp["net_pnl"] < 0]["net_pnl"].sum())
        s_pf = s_wins / s_losses if s_losses > 0 else float("inf")
        s_wr = (grp["net_pnl"] > 0).mean() * 100
        s_pnl = grp["net_pnl"].sum()
        s_mae = grp["mae_atr"].mean()
        print(f"| {sb:<25} | {len(grp)} | {s_wr:.1f}% | {s_pf:.2f} | ${s_pnl:+,.2f} | {s_mae:.2f} |")

    # 3. Joint Gating: Entry Ratio >= 1.0 (entered beyond/at extension) & Volatility Width
    print("\n==================================================")
    print("WIDTH GATING FOR DEEP ENTRIES (Entry Ratio >= 1.0)")
    print("==================================================")
    deep_df["width_bucket"] = np.where(deep_df["basis_to_extension_px"] <= 15.0, "Narrow (<=15 pts)",
                                       np.where(deep_df["basis_to_extension_px"] <= 30.0, "Medium (15-30 pts)", "Wide (>30 pts)"))
    print("| Width Bucket | Trades | Win Rate | Profit Factor | Net PnL ($) | Mean MAE (ATR) |")
    print("| :--- | :---: | :---: | :---: | :---: | :---: |")
    for wb, grp in deep_df.groupby("width_bucket"):
        w_wins = grp[grp["net_pnl"] > 0]["net_pnl"].sum()
        w_losses = abs(grp[grp["net_pnl"] < 0]["net_pnl"].sum())
        w_pf = w_wins / w_losses if w_losses > 0 else float("inf")
        w_wr = (grp["net_pnl"] > 0).mean() * 100
        w_pnl = grp["net_pnl"].sum()
        w_mae = grp["mae_atr"].mean()
        print(f"| {wb:<18} | {len(grp)} | {w_wr:.1f}% | {w_pf:.2f} | ${w_pnl:+,.2f} | {w_mae:.2f} |")

if __name__ == "__main__":
    run_analysis()
