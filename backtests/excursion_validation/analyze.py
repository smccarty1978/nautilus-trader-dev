import pandas as pd
from pathlib import Path
import matplotlib.pyplot as plt

def main():
    base_dir = Path("backtests/excursion_validation/results")
    dfs = []
    for yr in range(2020, 2027):
        p = base_dir / f"live_{yr}" / "trades.parquet"
        if p.exists():
            df = pd.read_parquet(p)
            df["year"] = yr
            dfs.append(df)
            
    if not dfs:
        print("No trades found.")
        return
        
    all_trades = pd.concat(dfs, ignore_index=True)
    
    print("=== EXCURSION NT VALIDATION RESULTS (2020-2026) ===\n")
    print(f"Total Trades: {len(all_trades):,}")
    
    # 1. Overall PT vs SL
    win_rate = (all_trades["exit_reason"] == "target").mean()
    print(f"Overall Win Rate (+1 ATR vs -1 ATR): {win_rate:.2%}")
    
    # Time in trade (seconds)
    all_trades["hold_s"] = (all_trades["exit_ts"] - all_trades["entry_ts"]) / 1e9
    
    print("\n--- PERFORMANCE BY EXCURSION BUCKET ---")
    
    buckets = ["low", "mid", "high"]
    for bkt in buckets:
        b_df = all_trades[all_trades["excursion_bkt"] == bkt]
        if len(b_df) == 0:
            continue
            
        wr = (b_df["exit_reason"] == "target").mean()
        gross = b_df["gross_pnl"].sum()
        net = b_df["net_pnl"].sum()
        ev = b_df["net_pnl"].mean()
        hold = b_df["hold_s"].median()
        
        l_pct = (b_df["direction"] == 1).mean()
        
        print(f"\n[{bkt.upper()} EXCURSION]")
        print(f"  Trades     : {len(b_df):,}")
        print(f"  Win Rate   : {wr:.2%} (PT vs SL)")
        print(f"  Total Net  : ${net:,.2f}  (Gross: ${gross:,.2f})")
        print(f"  EV/Trade   : ${ev:,.2f}")
        print(f"  Hold Time  : {hold:.1f}s (median)")
        print(f"  Long/Short : {l_pct:.0%} Long / {1-l_pct:.0%} Short")
        
        # Yearly stability
        print("  Yearly Win Rates:")
        for yr in range(2020, 2027):
            y_df = b_df[b_df["year"] == yr]
            if len(y_df) > 0:
                y_wr = (y_df["exit_reason"] == "target").mean()
                print(f"    {yr}: {y_wr:.2%} (n={len(y_df)})")

    # Trade Clustering
    # Calculate how often trades happen within X minutes of each other
    # Sort by entry_ts
    for bkt in buckets:
        b_df = all_trades[all_trades["excursion_bkt"] == bkt].sort_values("entry_ts")
        if len(b_df) > 1:
            diff_m = b_df["entry_ts"].diff() / 1e9 / 60
            clustered = (diff_m < 30).mean()
            print(f"\n{bkt.upper()} Clustering: {clustered:.1%} of trades occur within 30m of prior trade in same bucket.")

if __name__ == "__main__":
    main()
