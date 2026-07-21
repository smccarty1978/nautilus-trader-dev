import os, sys
from pathlib import Path
import pandas as pd
import numpy as np

PROJECT_ROOT = Path("c:/Users/Scott McCarty/Projects/Nautilus Trader")
sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)

def main():
    print("Loading 1s NQ bars for 2025...")
    df_1s = pd.read_parquet("data/raw/NQ_v0_1s_2025.parquet")
    
    print("Resampling to 1m bars...")
    df_1m = pd.DataFrame()
    df_1m["open"] = df_1s["open"].resample("1Min").first()
    df_1m["high"] = df_1s["high"].resample("1Min").max()
    df_1m["low"] = df_1s["low"].resample("1Min").min()
    df_1m["close"] = df_1s["close"].resample("1Min").last()
    df_1m = df_1m.dropna()
    
    # Load trades and flips
    df_trades = pd.read_parquet("backtests/baseline_flip_parity/results/nq_live_2025_base/trades.parquet")
    df_flips = pd.read_parquet("studies/regime_classification/results/flips_excursion_paths.parquet")
    df_flips_2025 = df_flips[df_flips["year"] == 2025].copy()
    
    df_trades["flip_ts"] = df_trades["entry_ts"] - 60 * 1_000_000_000
    df_m = df_trades.merge(
        df_flips_2025,
        left_on=["flip_ts", "signal_direction"],
        right_on=["entry_ts", "signal_direction"],
        how="inner"
    )
    
    df_false = df_m[df_m["bar1_confirm"] == False]
    print(f"Found {len(df_false)} false-confirmed trades in 2025.\n")
    
    # Check first 5 false-confirmed trades
    count = 0
    for _, row in df_false.head(10).iterrows():
        flip_ts = int(row["flip_ts"])
        entry_ts = int(row["entry_ts_x"])
        d = int(row["signal_direction"])
        
        t_flip = pd.Timestamp(flip_ts, unit="ns", tz="UTC")
        t_entry = pd.Timestamp(entry_ts, unit="ns", tz="UTC")
        
        # Look up 1m bars
        fb = df_1m.loc[t_flip]
        b1 = df_1m.loc[t_flip + pd.Timedelta(minutes=1)] # Wait, is this the bar starting at flip_ts, which closes at entry_ts?
        # Let's print both
        
        fb_h, fb_l = fb["high"], fb["low"]
        b1_h, b1_l = b1["high"], b1["low"]
        b1_o, b1_c = b1["open"], b1["close"]
        
        if d == 1:
            high_break = b1_h > fb_h
            bullish_bar = b1_c > b1_o
            print(f"Long flip at {t_flip}:")
            print(f"  Flip Bar (starts {t_flip}): high={fb_h:.2f}")
            print(f"  Bar1 (starts {t_flip + pd.Timedelta(minutes=1)}): open={b1_o:.2f}, high={b1_h:.2f}, close={b1_c:.2f}")
            print(f"  High break: {high_break} (need True) | Bullish bar: {bullish_bar} (need True for offline)")
        else:
            low_break = b1_l < fb_l
            bearish_bar = b1_c < b1_o
            print(f"Short flip at {t_flip}:")
            print(f"  Flip Bar (starts {t_flip}): low={fb_l:.2f}")
            print(f"  Bar1 (starts {t_flip + pd.Timedelta(minutes=1)}): open={b1_o:.2f}, low={b1_l:.2f}, close={b1_c:.2f}")
            print(f"  Low break: {low_break} (need True) | Bearish bar: {bearish_bar} (need True for offline)")
            
        print("-" * 80)

if __name__ == "__main__":
    main()
