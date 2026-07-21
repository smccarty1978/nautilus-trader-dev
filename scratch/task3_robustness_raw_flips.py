"""Task 3 Robustness on Raw Flips."""
import pandas as pd
import numpy as np
from pathlib import Path

PROJECT_ROOT = Path("c:/Users/Scott McCarty/Projects/Nautilus Trader")
RESULTS_DIR = PROJECT_ROOT / "backtests/hmm_state_filtered/results"
OOS_YEARS = [2023, 2024, 2025, 2026]
NQ_MULT = 20.0
COMM_PER_CTR_RT = 5.0

def main():
    print("Loading raw flips baseline trades for Task 3...")
    all_trades = []
    
    for y in OOS_YEARS:
        p = RESULTS_DIR / f"nq_hmm_4_s3_pt2p0_ancflip_flip_p4_minatr15p0_{y}/trades.parquet"
        if not p.exists():
            continue
        df = pd.read_parquet(p)
        df["pnl"] = (df["exit_px"] - df["entry_px"]) * df["signal_direction"] * NQ_MULT - COMM_PER_CTR_RT
        df["year"] = y
        df["date"] = pd.to_datetime(df["entry_ts"], unit="ns", utc=True).dt.tz_convert("America/New_York")
        df["month"] = df["date"].dt.to_period("M")
        all_trades.append(df)
        
    oos_df = pd.concat(all_trades).sort_values("entry_ts").reset_index(drop=True)
    print(f"Total raw flip OOS trade records loaded: {len(oos_df)}")
    
    # Monthly P&L breakdown
    monthly_pnl = oos_df.groupby("month")["pnl"].agg(["sum", "count"]).rename(columns={"sum": "net_pnl", "count": "trades"})
    print("\n--- Monthly P&L Breakdown (Raw Flips) ---")
    print(monthly_pnl.to_string())
    
    # Identify top monthly clusters in 2023 and 2025
    m2023 = monthly_pnl[monthly_pnl.index.astype(str).str.startswith("2023")].sort_values("net_pnl", ascending=False)
    top_2023_month = m2023.index[0]
    
    m2025 = monthly_pnl[monthly_pnl.index.astype(str).str.startswith("2025")].sort_values("net_pnl", ascending=False)
    top_2025_month1 = m2025.index[0]
    top_2025_month2 = m2025.index[1]
    
    # Exclusion sweeps
    print("\n======================================================================")
    print("  RAW FLIPS EXCLUSION SWEEPS")
    print("======================================================================")
    print(f"Baseline Pooled OOS: Net PnL = ${oos_df['pnl'].sum():,.2f}  Avg $/tr = ${oos_df['pnl'].mean():.2f} (n={len(oos_df)})")
    
    # Drop Aug-Oct 2024
    drop_2024_cluster = ["2024-08", "2024-09", "2024-10"]
    df_ex1 = oos_df[~oos_df["month"].astype(str).isin(drop_2024_cluster)]
    print(f"Drop Aug-Oct 2024 loss cluster: Net PnL = ${df_ex1['pnl'].sum():,.2f}  Avg $/tr = ${df_ex1['pnl'].mean():.2f} (n={len(df_ex1)})")
    
    # Drop top 2023 month
    df_ex2 = oos_df[oos_df["month"] != top_2023_month]
    print(f"Drop top 2023 profit month ({top_2023_month}): Net PnL = ${df_ex2['pnl'].sum():,.2f}  Avg $/tr = ${df_ex2['pnl'].mean():.2f} (n={len(df_ex2)})")
    
    # Drop top 2025 month 1
    df_ex3 = oos_df[oos_df["month"] != top_2025_month1]
    print(f"Drop top 2025 profit month 1 ({top_2025_month1}): Net PnL = ${df_ex3['pnl'].sum():,.2f}  Avg $/tr = ${df_ex3['pnl'].mean():.2f} (n={len(df_ex3)})")
    
    # Drop top 2025 month 1 & 2
    df_ex4 = oos_df[~oos_df["month"].isin([top_2025_month1, top_2025_month2])]
    print(f"Drop top 2025 profit months 1 & 2 ({top_2025_month1}, {top_2025_month2}): Net PnL = ${df_ex4['pnl'].sum():,.2f}  Avg $/tr = ${df_ex4['pnl'].mean():.2f} (n={len(df_ex4)})")
    
    # Drop BOTH 2024 loss cluster and top 2025 profit month 1
    df_ex5 = oos_df[~oos_df["month"].astype(str).isin(drop_2024_cluster + [str(top_2025_month1)])]
    print(f"Drop BOTH 2024 loss cluster AND top 2025 profit month 1: Net PnL = ${df_ex5['pnl'].sum():,.2f}  Avg $/tr = ${df_ex5['pnl'].mean():.2f} (n={len(df_ex5)})")

if __name__ == "__main__":
    main()
