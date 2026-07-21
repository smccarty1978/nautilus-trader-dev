"""Task 4 Volatility Gate on Raw Flips."""
import pandas as pd
import numpy as np
from pathlib import Path

PROJECT_ROOT = Path("c:/Users/Scott McCarty/Projects/Nautilus Trader")
RESULTS_DIR = PROJECT_ROOT / "backtests/hmm_state_filtered/results"
OOS_YEARS = [2023, 2024, 2025, 2026]
NQ_MULT = 20.0
COMM_PER_CTR_RT = 5.0

def load_all_trades():
    all_trades = []
    for y in OOS_YEARS:
        p = RESULTS_DIR / f"nq_hmm_4_s3_pt2p0_ancflip_flip_p4_minatr15p0_{y}/trades.parquet"
        if not p.exists():
            continue
        df = pd.read_parquet(p)
        df["pnl"] = (df["exit_px"] - df["entry_px"]) * df["signal_direction"] * NQ_MULT - COMM_PER_CTR_RT
        df["year"] = y
        all_trades.append(df)
    return pd.concat(all_trades).reset_index(drop=True)

def analyze_gate(df, min_atr_threshold):
    filtered_df = df[df["entry_atr"] >= min_atr_threshold]
    
    yearly_stats = {}
    for y in OOS_YEARS:
        y_df = filtered_df[filtered_df["year"] == y]
        n = len(y_df)
        if n == 0:
            yearly_stats[y] = {"records": 0, "net_pnl": 0.0, "win_rate": 0.0, "avg_pnl": 0.0}
            continue
        net_pnl = y_df["pnl"].sum()
        win_rate = (y_df["pnl"] > 0).mean()
        avg_pnl = y_df["pnl"].mean()
        yearly_stats[y] = {"records": n, "net_pnl": net_pnl, "win_rate": win_rate, "avg_pnl": avg_pnl}
        
    pooled_net = filtered_df["pnl"].sum()
    pooled_wr = (filtered_df["pnl"] > 0).mean() if len(filtered_df) > 0 else 0.0
    pooled_avg = filtered_df["pnl"].mean() if len(filtered_df) > 0 else 0.0
    
    return yearly_stats, {"records": len(filtered_df), "net_pnl": pooled_net, "win_rate": pooled_wr, "avg_pnl": pooled_avg}

def main():
    print("Loading raw flips trades for Task 4...")
    df = load_all_trades()
    print(f"Total trades: {len(df)}")
    
    thresholds = [15.0, 18.0, 20.0, 22.0, 25.0, 30.0]
    
    print("\n======================================================================")
    print("  RAW FLIPS VOLATILITY THRESHOLD SWEEP RESULTS")
    print("======================================================================")
    
    for t in thresholds:
        yearly, pooled = analyze_gate(df, t)
        print(f"\nThreshold ATR >= {t:.1f}:")
        print(f"  Pooled: Records={pooled['records']:<4} WR={pooled['win_rate']:>5.1%} NetPnL=${pooled['net_pnl']:>+9.2f} AvgPnL=${pooled['avg_pnl']:>+6.2f}")
        for y in OOS_YEARS:
            y_stat = yearly[y]
            print(f"    Year {y}: Records={y_stat['records']:<4} WR={y_stat['win_rate']:>5.1%} NetPnL=${y_stat['net_pnl']:>+9.2f} AvgPnL=${y_stat['avg_pnl']:>+6.2f}")

if __name__ == "__main__":
    main()
