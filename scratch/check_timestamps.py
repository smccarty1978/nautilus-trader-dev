import os, sys
from pathlib import Path
import pandas as pd
import numpy as np

PROJECT_ROOT = Path("c:/Users/Scott McCarty/Projects/Nautilus Trader")
sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)

# Load 1s bars for 2023 to verify exact seconds
from scratch.calculate_conditioning_features import load_1s
bars_1s = load_1s(2023)
print("Loaded 1s bars for 2023. Total rows:", len(bars_1s))

# Load a sample trade from predict_bar1_excursions
df = pd.read_parquet("scratch/predict_bar1_excursions.parquet")
df_2023 = df[df["year"] == 2023]
print("Total 2023 trades in excursions:", len(df_2023))

# Print first 5 trades with details
for idx, row in df_2023.head(5).iterrows():
    entry_ts = int(row["entry_ts"])
    entry_ts_bar1 = int(row["entry_ts_bar1"])
    entry_px_bar1 = row["entry_px_bar1"]
    
    # Retrieve 1s bars around the timestamps
    t_start = entry_ts - 5 * 10**9
    t_end = entry_ts_bar1 + 5 * 10**9
    t_start_ts = pd.Timestamp(t_start, unit='ns', tz='UTC')
    t_end_ts = pd.Timestamp(t_end, unit='ns', tz='UTC')
    sub_bars = bars_1s.loc[t_start_ts:t_end_ts]
    
    print("\n" + "="*60)
    print(f"Trade ID: {idx} | Direction: {row['signal_direction']}")
    print(f"entry_ts:      {pd.to_datetime(entry_ts, unit='ns', utc=True)} ({entry_ts})")
    print(f"entry_ts_bar1: {pd.to_datetime(entry_ts_bar1, unit='ns', utc=True)} ({entry_ts_bar1})")
    print(f"entry_px_bar1: {entry_px_bar1}")
    print("\nRelevant 1s bars:")
    for t, r in sub_bars.iterrows():
        # Highlight matches
        match_str = ""
        if t.value == entry_ts:
            match_str = " <-- entry_ts"
        elif t.value == entry_ts_bar1:
            match_str = " <-- entry_ts_bar1"
            
        px_match = ""
        if abs(r["close"] - entry_px_bar1) < 1e-5:
            px_match = f" <-- MATCHES entry_px_bar1 ({r['close']})"
            
        print(f"  {pd.to_datetime(t.value, unit='ns', utc=True)} | Close: {r['close']}{match_str}{px_match}")
