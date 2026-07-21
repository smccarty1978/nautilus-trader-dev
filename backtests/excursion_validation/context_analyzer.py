import pandas as pd
import numpy as np
from pathlib import Path

def main():
    base_dir = Path("backtests/excursion_validation/results")
    dfs = []
    for yr in range(2020, 2027):
        p = base_dir / f"live_{yr}" / "trades.parquet"
        if p.exists():
            df = pd.read_parquet(p)
            df = df[df["excursion_bkt"] == "low"].copy()
            df["year"] = yr
            dfs.append(df)
            
    trades = pd.concat(dfs, ignore_index=True)
    
    # 1. Time-based features
    # entry_ts is in nanoseconds UTC
    trades["entry_dt"] = pd.to_datetime(trades["entry_ts"], unit='ns', utc=True).dt.tz_convert('America/Chicago')
    trades["time_str"] = trades["entry_dt"].dt.strftime("%H:%M")
    trades["date_str"] = trades["entry_dt"].dt.strftime("%Y-%m-%d")
    
    # Time buckets (Chicago Time: RTH is 08:30 to 15:00)
    # AM Open: 08:30 - 10:00 CT
    # Midday: 10:00 - 13:00 CT
    # PM: 13:00 - 15:00 CT
    def get_bucket(t):
        if "08:30" <= t < "10:00": return "AM_Open"
        if "10:00" <= t < "13:00": return "Midday"
        if "13:00" <= t < "15:00": return "PM_Trend"
        return "Overnight"
        
    trades["time_bkt"] = trades["time_str"].apply(get_bucket)
    
    # Trade Sequence (first flip of day)
    trades = trades.sort_values("entry_ts")
    trades["trade_seq"] = trades.groupby("date_str").cumcount() + 1
    
    # Output the initial non-VWAP features
    print("=== CONTEXTUAL ANALYSIS (LOW EXCURSION ONLY) ===")
    print(f"Total Low Excursion Trades: {len(trades)}")
    
    win = trades["exit_reason"] == "target"
    print("\n--- By Time Bucket ---")
    for bkt in ["AM_Open", "Midday", "PM_Trend"]:
        mask = trades["time_bkt"] == bkt
        if mask.sum() > 0:
            wr = win[mask].mean()
            print(f"  {bkt:10s}: {wr:.2%} (n={mask.sum()})")
            
    print("\n--- By Trade Sequence ---")
    mask_first = trades["trade_seq"] == 1
    mask_second = trades["trade_seq"] == 2
    mask_late = trades["trade_seq"] > 2
    print(f"  1st Flip of Day : {win[mask_first].mean():.2%} (n={mask_first.sum()})")
    print(f"  2nd Flip of Day : {win[mask_second].mean():.2%} (n={mask_second.sum()})")
    print(f"  3rd+ Flip of Day: {win[mask_late].mean():.2%} (n={mask_late.sum()})")
    
    # Volatility
    median_atr = trades["atr_at_signal"].median()
    mask_low_vol = trades["atr_at_signal"] < median_atr
    mask_high_vol = trades["atr_at_signal"] >= median_atr
    print(f"\n--- By ATR Regime (Median = {median_atr:.2f}) ---")
    print(f"  Low Volatility  : {win[mask_low_vol].mean():.2%} (n={mask_low_vol.sum()})")
    print(f"  High Volatility : {win[mask_high_vol].mean():.2%} (n={mask_high_vol.sum()})")

if __name__ == "__main__":
    main()
