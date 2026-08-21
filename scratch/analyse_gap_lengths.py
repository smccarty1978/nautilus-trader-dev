import pandas as pd
import numpy as np

# Let's inspect the lengths in NQ_v0_1s_2016
# We can load the results or calculate them
# Since we didn't write all_lengths_all to a file, let's write a small script to calculate and analyze
import os
import glob
import pyarrow.parquet as pq
import pandas_market_calendars as mcal

cal = mcal.get_calendar('CME_Equity')
raw_file = r"C:\Users\Scott McCarty\Projects\Nautilus Trader\data\raw\NQ_v0_1s_2016.parquet"
table = pq.read_table(raw_file, columns=['ts_event'])
native_df = table.to_pandas()
native_ts = native_df.index.unique().sort_values()
schedule = cal.schedule(start_date='2016-01-01', end_date='2016-12-31')

all_lengths = []
for idx, row in schedule.iterrows():
    open_val = row['market_open']
    close_val = row['market_close']
    break_start = row.get('break_start', pd.NaT)
    break_end = row.get('break_end', pd.NaT)
    
    intervals = []
    end1 = break_start if pd.notna(break_start) and break_start > open_val else close_val
    if open_val < end1:
        intervals.append((open_val, end1))
    if pd.notna(break_end) and break_end < close_val:
        intervals.append((break_end, close_val))
        
    for start, end in intervals:
        expected_sub = pd.date_range(start=start, end=end - pd.Timedelta(seconds=1), freq='s')
        if len(expected_sub) == 0:
            continue
        idx_start = np.searchsorted(native_ts, start, side='left')
        idx_end = np.searchsorted(native_ts, end, side='left')
        native_sub = native_ts[idx_start:idx_end]
        missing_mask = ~expected_sub.isin(native_sub)
        if missing_mask.any():
            padded = np.empty(len(missing_mask) + 2, dtype=bool)
            padded[0] = False
            padded[-1] = False
            padded[1:-1] = missing_mask
            diff = np.diff(padded.astype(int))
            run_starts = np.where(diff == 1)[0]
            run_ends = np.where(diff == -1)[0]
            all_lengths.extend(run_ends - run_starts)

all_lengths = np.array(all_lengths)
print(f"Total gaps: {len(all_lengths)}")
print(f"Gaps > 30s: {np.sum(all_lengths > 30)}")
print(f"Gaps > 60s: {np.sum(all_lengths > 60)}")
print(f"Gaps > 300s (5m): {np.sum(all_lengths > 300)}")
print(f"Gaps > 1800s (30m): {np.sum(all_lengths > 1800)}")
print(f"Gaps > 3600s (1h): {np.sum(all_lengths > 3600)}")
print(f"Gaps > 14400s (4h): {np.sum(all_lengths > 14400)}")
print(f"Gaps > 43200s (12h): {np.sum(all_lengths > 43200)}")
