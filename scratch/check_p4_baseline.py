"""Load and analyze existing production baseline backtests."""
import pandas as pd
import numpy as np
from pathlib import Path

PROJECT_ROOT = Path("c:/Users/Scott McCarty/Projects/Nautilus Trader")
RESULTS_DIR = PROJECT_ROOT / "backtests/hmm_state_filtered/results"
OOS_YEARS = [2023, 2024, 2025, 2026]
NQ_MULT = 20.0
COMM_PER_CTR_RT = 5.0

def main():
    print("Analyzing baseline nq_hmm_4_s3_pt2p0 across OOS years...")
    all_trades = []
    
    for y in OOS_YEARS:
        folder = RESULTS_DIR / f"nq_hmm_4_s3_pt2p0_{y}"
        p = folder / "trades.parquet"
        if not p.exists():
            print(f"Year {y}: {p} not found!")
            continue
            
        df = pd.read_parquet(p)
        df["year"] = y
        # Calculate PnL per contract record
        df["pnl"] = (df["exit_px"] - df["entry_px"]) * df["signal_direction"] * NQ_MULT - COMM_PER_CTR_RT
        all_trades.append(df)
        
        # Calculate yearly stats
        n_records = len(df)
        net_pnl = df["pnl"].sum()
        win_rate = (df["pnl"] > 0).mean()
        gp = df[df["pnl"] > 0]["pnl"].sum()
        gl = abs(df[df["pnl"] < 0]["pnl"].sum())
        pf = gp / gl if gl > 0 else np.nan
        avg_pnl_tr = df["pnl"].mean()
        
        print(f"Year {y}: Records={n_records:>3}  WinRate={win_rate:>6.1%}  NetPnL=${net_pnl:>+9.2f}  AvgPnL/Tr=${avg_pnl_tr:>+7.2f}  PF={pf:>4.2f}")
        
    if not all_trades:
        print("No trades found.")
        return
        
    oos_df = pd.concat(all_trades)
    print("\nPooled OOS Metrics (2023-2026):")
    print(f"  Total Records: {len(oos_df)}")
    print(f"  Win Rate:      {(oos_df['pnl'] > 0).mean():.1%}")
    print(f"  Net PnL ($):   ${oos_df['pnl'].sum():,.2f}")
    print(f"  Avg PnL/Tr:    ${oos_df['pnl'].mean():.2f}")
    
if __name__ == "__main__":
    main()
