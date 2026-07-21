"""Task 5: Block Bootstrap Test and Verification."""
import pandas as pd
import numpy as np
from pathlib import Path

PROJECT_ROOT = Path("c:/Users/Scott McCarty/Projects/Nautilus Trader")
RESULTS_DIR = PROJECT_ROOT / "backtests/hmm_state_filtered/results"
OOS_YEARS = [2023, 2024, 2025, 2026]
NQ_MULT = 20.0
COMM_PER_CTR_RT = 5.0

def load_and_deduplicate(prefix: str):
    all_trades = []
    for y in OOS_YEARS:
        folder = RESULTS_DIR / f"{prefix}_{y}"
        p = folder / "trades.parquet"
        if not p.exists():
            continue
        df = pd.read_parquet(p)
        df["pnl"] = (df["exit_px"] - df["entry_px"]) * df["signal_direction"] * NQ_MULT - COMM_PER_CTR_RT
        df["year"] = y
        df["date"] = pd.to_datetime(df["entry_ts"], unit="ns", utc=True).dt.tz_convert("America/New_York")
        df["month"] = df["date"].dt.to_period("M")
        all_trades.append(df)
        
    df_all = pd.concat(all_trades).reset_index(drop=True)
    print(f"Loaded raw records count: {len(df_all)}")
    
    # Deduplicate by grouping by entry_ts
    # Sum the PnL of the duplicate records (c1/c2 dual contracts)
    # Average the entry_atr, etc.
    dedup = df_all.groupby("entry_ts").agg({
        "pnl": "sum",
        "entry_atr": "first",
        "year": "first",
        "month": "first",
        "signal_direction": "first"
    }).reset_index()
    
    print(f"Deduplicated trades count: {len(dedup)}")
    return dedup

def main():
    print("Testing Bar 1 Confirmed cohort...")
    dedup = load_and_deduplicate("nq_hmm_4_s3_pt2p0")
    
    # Compute per-trade std of the summed PnL
    per_trade_std = dedup["pnl"].std()
    print(f"Per-trade std of net PnL (summed contracts): ${per_trade_std:.2f}")
    
    # Let's check single-contract std
    single_std = (dedup["pnl"] / 2.0).std()
    print(f"Single-contract std of net PnL: ${single_std:.2f}")

if __name__ == "__main__":
    main()
