import os
import pandas as pd
import glob
import pytz
import pyarrow.parquet as pq

raw_dir = r"C:\Users\Scott McCarty\Projects\Nautilus Trader\data\raw"
pattern = os.path.join(raw_dir, "NQ_v0_1s_*.parquet")
files = sorted(glob.glob(pattern))

tz_chicago = pytz.timezone("America/Chicago")

print(f"Found {len(files)} NQ 1s files:")
total_native_rows = 0
min_ts = None
max_ts = None

for f in files:
    filename = os.path.basename(f)
    pf = pq.ParquetFile(f)
    num_rows = pf.metadata.num_rows
    total_native_rows += num_rows
    
    # Read first and last row
    first_table = pf.read_row_group(0)
    last_table = pf.read_row_group(pf.num_row_groups - 1)
    
    df_first = first_table.to_pandas()
    df_last = last_table.to_pandas()
    
    # Extract timestamp from index or column
    def extract_ts(df, position):
        if 'ts_event' in df.columns:
            val = df['ts_event'].iloc[position]
        elif df.index.name == 'ts_event':
            val = df.index[position]
        elif 'timestamp' in df.columns:
            val = df['timestamp'].iloc[position]
        elif df.index.name == 'timestamp':
            val = df.index[position]
        else:
            val = df.index[position]
        
        # Parse it to a tz-aware Timestamp in UTC
        if isinstance(val, (int, float)):
            ts = pd.Timestamp(val, unit='ns', tz='UTC')
        else:
            ts = pd.Timestamp(val)
            if ts.tzinfo is None:
                ts = ts.tz_localize('UTC')
            else:
                ts = ts.tz_convert('UTC')
        return ts

    first_ts = extract_ts(df_first, 0)
    last_ts = extract_ts(df_last, -1)
    
    if min_ts is None or first_ts < min_ts:
        min_ts = first_ts
    if max_ts is None or last_ts > max_ts:
        max_ts = last_ts
        
    print(f"File: {filename}")
    print(f"  Rows: {num_rows:,}")
    print(f"  First: {first_ts} ({first_ts.tz_convert(tz_chicago)})")
    print(f"  Last:  {last_ts} ({last_ts.tz_convert(tz_chicago)})")

print("\nSummary:")
print(f"Total Native Rows: {total_native_rows:,}")
print(f"Global First: {min_ts} ({min_ts.tz_convert(tz_chicago) if min_ts else None})")
print(f"Global Last:  {max_ts} ({max_ts.tz_convert(tz_chicago) if max_ts else None})")
