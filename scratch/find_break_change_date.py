import pandas as pd
import numpy as np
import pytz

f_1s = r"C:\Users\Scott McCarty\Projects\Nautilus Trader\data\raw\NQ_v0_1s_2020.parquet"
df = pd.read_parquet(f_1s, columns=['volume'])
df.index = pd.to_datetime(df.index)

tz_chicago = pytz.timezone('America/Chicago')
df_chi = df.index.tz_convert(tz_chicago)

# Check dates in 2020 where trades occurred between 15:15:00 and 15:29:59 Chicago time
hours = df_chi.hour
minutes = df_chi.minute
seconds = df_chi.second

time_in_seconds = hours * 3600 + minutes * 60 + seconds
rth_break_start = 15 * 3600 + 15 * 60
rth_break_end = 15 * 3600 + 30 * 60

is_during_break = (time_in_seconds >= rth_break_start) & (time_in_seconds < rth_break_end)

# Find dates with trades during break
dates_with_trades = pd.Series(df_chi[is_during_break].date).unique()
print("Dates in 2020 with trades during 15:15-15:30 CT:")
print(dates_with_trades[:20])
print("...")
print(dates_with_trades[-10:])
