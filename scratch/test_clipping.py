import os
import glob
import time
import json
import numpy as np
import pandas as pd
import pytz
import pyarrow.parquet as pq
import pandas_market_calendars as mcal

cal = mcal.get_calendar('CME_Equity')
tz_chicago = pytz.timezone('America/Chicago')

raw_dir = r"C:\Users\Scott McCarty\Projects\Nautilus Trader\data\raw"
pattern = os.path.join(raw_dir, "NQ_v0_1s_*.parquet")
files = sorted(glob.glob(pattern))

for f in files:
    filename = os.path.basename(f)
    year_str = filename.split('_')[3].split('.')[0]
    year_val = 2026 if 'ytd' in year_str else int(year_str)
    
    pf = pq.ParquetFile(f)
    table = pq.read_table(f, columns=['ts_event'])
    native_df = table.to_pandas()
    native_ts = native_df.index.unique().sort_values()
    
    first_native = native_ts[0]
    last_native = native_ts[-1]
    
    # Query schedule for this year
    schedule = cal.schedule(start_date=first_native.date().isoformat(), end_date=last_native.date().isoformat())
    
    expected_ts_list = []
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
            
            # Clip expected_sub to [first_native, last_native]
            expected_sub = expected_sub[(expected_sub >= first_native) & (expected_sub <= last_native)]
            if len(expected_sub) > 0:
                expected_ts_list.append(expected_sub)
                
    if not expected_ts_list:
        print(f"Year {year_val}: No expected seconds generated.")
        continue
        
    expected_ts = pd.DatetimeIndex(np.concatenate([idx.values for idx in expected_ts_list])).tz_localize('UTC')
    
    # Missing mask
    missing_mask = ~expected_ts.isin(native_ts)
    sub_missing_count = missing_mask.sum()
    
    # Gap runs
    if sub_missing_count > 0:
        padded = np.empty(len(missing_mask) + 2, dtype=bool)
        padded[0] = False
        padded[-1] = False
        padded[1:-1] = missing_mask
        
        diff = np.diff(padded.astype(int))
        run_starts = np.where(diff == 1)[0]
        run_ends = np.where(diff == -1)[0]
        
        run_lengths = run_ends - run_starts
        gaps_over_30 = np.sum(run_lengths > 30)
        print(f"Year {year_val}: expected={len(expected_ts):,}, missing={sub_missing_count:,}, gaps={len(run_lengths):,}, gaps>30s={gaps_over_30:,}")
    else:
        print(f"Year {year_val}: expected={len(expected_ts):,}, missing=0, gaps=0")
