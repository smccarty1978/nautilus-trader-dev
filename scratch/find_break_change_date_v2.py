import pandas as pd
import numpy as np
import pytz
import os

tz_chicago = pytz.timezone('America/Chicago')
raw_dir = r"C:\Users\Scott McCarty\Projects\Nautilus Trader\data\raw"

for yr in [2020, 2021]:
    f = os.path.join(raw_dir, f"NQ_v0_1s_{yr}.parquet")
    df = pd.read_parquet(f, columns=['volume'])
    df.index = pd.to_datetime(df.index)
    
    df_chi = df.index.tz_convert(tz_chicago)
    hours = df_chi.hour
    minutes = df_chi.minute
    seconds = df_chi.second
    
    time_in_seconds = hours * 3600 + minutes * 60 + seconds
    rth_break_start = 15 * 3600 + 15 * 60
    rth_break_end = 15 * 3600 + 30 * 60
    
    is_during_break = (time_in_seconds >= rth_break_start) & (time_in_seconds < rth_break_end)
    
    dates_with_trades = pd.Series(df_chi[is_during_break].date).value_counts().sort_index()
    print(f"\n--- Year {yr} ---")
    print(f"Number of days with trades during 15:15-15:30: {len(dates_with_trades)}")
    if len(dates_with_trades) > 0:
        print("First few days:")
        print(dates_with_trades.head(5))
        print("Last few days:")
        print(dates_with_trades.tail(5))
