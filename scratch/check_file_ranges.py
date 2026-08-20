import os
import glob
import time
import json
import numpy as np
import pandas as pd
import pytz
import pyarrow.parquet as pq
import pandas_market_calendars as mcal

def main():
    cal = mcal.get_calendar('CME_Equity')
    tz_chicago = pytz.timezone('America/Chicago')

    raw_dir = r"C:\Users\Scott McCarty\Projects\Nautilus Trader\data\raw"
    pattern = os.path.join(raw_dir, "NQ_v0_1s_*.parquet")
    files = sorted(glob.glob(pattern))

    file_metadata = {}
    
    # First, let's collect exact native boundaries for each file
    for f in files:
        filename = os.path.basename(f)
        year_str = filename.split('_')[3].split('.')[0]
        year_val = 2026 if 'ytd' in year_str else int(year_str)
        
        pf = pq.ParquetFile(f)
        row_count = pf.metadata.num_rows
        
        # Read first and last row
        first_table = pf.read_row_group(0)
        last_table = pf.read_row_group(pf.num_row_groups - 1)
        df_first = first_table.to_pandas()
        df_last = last_table.to_pandas()
        
        def extract_ts(df, pos):
            val = df.index[pos] if df.index.name == 'ts_event' else df['ts_event'].iloc[pos]
            return pd.Timestamp(val).tz_convert('UTC')
            
        first_ts = extract_ts(df_first, 0)
        last_ts = extract_ts(df_last, -1)
        
        file_metadata[year_val] = {
            'filename': filename,
            'first_ts': first_ts,
            'last_ts': last_ts,
            'row_count': row_count
        }
        print(f"File: {filename} | Year: {year_val} | Range: {first_ts} to {last_ts} | Rows: {row_count:,}")

    global_first = file_metadata[2016]['first_ts']
    global_last = file_metadata[2026]['last_ts']
    print(f"\nGlobal First: {global_first} | Global Last: {global_last}")

if __name__ == "__main__":
    main()
