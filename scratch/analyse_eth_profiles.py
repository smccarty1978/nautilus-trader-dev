import os
import glob
import time
import numpy as np
import pandas as pd
import pytz
import pyarrow.parquet as pq

def main():
    tz_chicago = pytz.timezone('America/Chicago')
    raw_dir = r"C:\Users\Scott McCarty\Projects\Nautilus Trader\data\raw"
    files = sorted(glob.glob(os.path.join(raw_dir, "NQ_v0_1s_*.parquet")))

    for f in files:
        filename = os.path.basename(f)
        year_str = filename.split('_')[3].split('.')[0]
        year_val = 2026 if 'ytd' in year_str else int(year_str)
        
        print(f"\nAnalyzing year {year_val}...", flush=True)
        t0 = time.time()
        
        # Read only index ts_event
        table = pq.read_table(f, columns=['ts_event'])
        df = table.to_pandas()
        ts = df.index.unique().sort_values()
        
        # Convert to Chicago
        ts_chi = ts.tz_convert(tz_chicago)
        
        # Group by date and minute of day
        dates = ts_chi.date
        minutes = ts_chi.hour * 60 + ts_chi.minute
        
        # Let's count unique dates
        unique_dates = np.unique(dates)
        num_dates = len(unique_dates)
        print(f"  Dates: {num_dates}, native rows: {len(ts):,}")
        
        # Create a coverage array: for each of the 1440 minutes, count how many dates had at least one observation
        # To do this efficiently, we can use a set of (date, minute)
        date_min_pairs = pd.Series(dates).astype(str) + "_" + pd.Series(minutes).astype(str)
        unique_pairs = date_min_pairs.unique()
        
        # Parse them back
        parsed_mins = [int(p.split('_')[1]) for p in unique_pairs]
        
        # Compute frequency of each minute of day
        min_counts = pd.Series(parsed_mins).value_counts().reindex(range(1440), fill_value=0)
        min_pct = min_counts / num_dates * 100.0
        
        # Let's print the minutes of day with 0% coverage or very low coverage
        # Let's group contiguous minutes with 0% coverage
        zero_mins = np.where(min_pct == 0.0)[0]
        if len(zero_mins) > 0:
            # group into runs
            runs = []
            start = zero_mins[0]
            prev = zero_mins[0]
            for m in zero_mins[1:]:
                if m == prev + 1:
                    prev = m
                else:
                    runs.append((start, prev))
                    start = m
                    prev = m
            runs.append((start, prev))
            
            print("  Contiguous 0% coverage minute intervals (Chicago time):")
            for r_start, r_end in runs:
                h_start, m_start = divmod(r_start, 60)
                h_end, m_end = divmod(r_end, 60)
                # length in minutes
                length = r_end - r_start + 1
                print(f"    {h_start:02d}:{m_start:02d} to {h_end:02d}:{m_end:02d} ({length} mins)")
        else:
            print("  No contiguous 0% coverage intervals found.")

if __name__ == "__main__":
    main()
