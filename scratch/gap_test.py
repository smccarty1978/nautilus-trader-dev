import os
import pandas as pd
import numpy as np
import pytz
import pyarrow.parquet as pq
import time
import pandas_market_calendars as mcal

t0 = time.time()
cal = mcal.get_calendar('CME_Equity')
tz_chicago = pytz.timezone('America/Chicago')

raw_file = r"C:\Users\Scott McCarty\Projects\Nautilus Trader\data\raw\NQ_v0_1s_2016.parquet"
print(f"Reading {raw_file}...", flush=True)

# Read index only
table = pq.read_table(raw_file, columns=['ts_event'])
native_df = table.to_pandas()
native_ts = native_df.index.unique().sort_values()

print(f"Loaded {len(native_ts):,} unique sorted native timestamps in {time.time() - t0:.1f}s", flush=True)

# Let's get the schedule for 2016
print("Generating schedule for 2016...", flush=True)
schedule = cal.schedule(start_date='2016-01-01', end_date='2016-12-31')
print(f"Schedule has {len(schedule)} trading dates.", flush=True)

total_expected_seconds = 0
total_missing_seconds = 0

expected_rth_seconds = 0
expected_eth_seconds = 0
missing_rth_seconds = 0
missing_eth_seconds = 0

rth_gap_runs = 0
eth_gap_runs = 0

# Count buckets
overall_buckets = {b: 0 for b in ['1s', '2s', '3-5s', '6-10s', '11-30s', '>30s']}
rth_buckets = {b: 0 for b in ['1s', '2s', '3-5s', '6-10s', '11-30s', '>30s']}
eth_buckets = {b: 0 for b in ['1s', '2s', '3-5s', '6-10s', '11-30s', '>30s']}

# For quantiles, we can collect all run lengths
rth_lengths_all = []
eth_lengths_all = []
all_lengths_all = []

unexplained_gaps_over_30s = []

t_gen_start = time.time()

for idx, row in schedule.iterrows():
    session_date = idx.date()
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
            
        # Find native timestamps in this interval
        idx_start = np.searchsorted(native_ts, start, side='left')
        idx_end = np.searchsorted(native_ts, end, side='left')
        native_sub = native_ts[idx_start:idx_end]
        
        # Missing mask
        missing_mask = ~expected_sub.isin(native_sub)
        
        # Stats
        sub_expected_count = len(expected_sub)
        sub_missing_count = missing_mask.sum()
        
        # Fast RTH/ETH classification using numpy
        expected_sec = expected_sub.values.astype('int64') // 10**9
        offset_sec = int(expected_sub[0].tz_convert(tz_chicago).utcoffset().total_seconds())
        chicago_sec = (expected_sec + offset_sec) % 86400
        
        rth_start_sec = 8 * 3600 + 30 * 60
        rth_end_sec = 15 * 3600 + 15 * 60
        
        is_rth_mask = (chicago_sec >= rth_start_sec) & (chicago_sec < rth_end_sec)
        
        sub_expected_rth = is_rth_mask.sum()
        sub_expected_eth = sub_expected_count - sub_expected_rth
        
        sub_missing_rth = (missing_mask & is_rth_mask).sum()
        sub_missing_eth = sub_missing_count - sub_missing_rth
        
        total_expected_seconds += sub_expected_count
        total_missing_seconds += sub_missing_count
        expected_rth_seconds += sub_expected_rth
        expected_eth_seconds += sub_expected_eth
        missing_rth_seconds += sub_missing_rth
        missing_eth_seconds += sub_missing_eth
        
        # Gap runs detection
        if sub_missing_count > 0:
            padded = np.empty(len(missing_mask) + 2, dtype=bool)
            padded[0] = False
            padded[-1] = False
            padded[1:-1] = missing_mask
            
            diff = np.diff(padded.astype(int))
            run_starts = np.where(diff == 1)[0]
            run_ends = np.where(diff == -1)[0]
            
            run_lengths = run_ends - run_starts
            run_is_rth = is_rth_mask[run_starts]
            
            rth_gap_runs += run_is_rth.sum()
            eth_gap_runs += (~run_is_rth).sum()
            
            rth_lengths_all.extend(run_lengths[run_is_rth])
            eth_lengths_all.extend(run_lengths[~run_is_rth])
            all_lengths_all.extend(run_lengths)
            
            # Count buckets
            def bin_lengths(lengths, buckets_dict):
                for length in lengths:
                    if length == 1:
                        buckets_dict['1s'] += 1
                    elif length == 2:
                        buckets_dict['2s'] += 1
                    elif 3 <= length <= 5:
                        buckets_dict['3-5s'] += 1
                    elif 6 <= length <= 10:
                        buckets_dict['6-10s'] += 1
                    elif 11 <= length <= 30:
                        buckets_dict['11-30s'] += 1
                    else:
                        buckets_dict['>30s'] += 1

            bin_lengths(run_lengths, overall_buckets)
            bin_lengths(run_lengths[run_is_rth], rth_buckets)
            bin_lengths(run_lengths[~run_is_rth], eth_buckets)
            
            # Record individual gaps > 30 seconds
            long_runs_idx = np.where(run_lengths > 30)[0]
            for r_idx in long_runs_idx:
                r_start_idx = run_starts[r_idx]
                r_end_idx = run_ends[r_idx]
                r_len = run_lengths[r_idx]
                
                gap_start_utc = expected_sub[r_start_idx]
                gap_end_utc = expected_sub[r_end_idx - 1]
                
                gap_start_chi = gap_start_utc.tz_convert(tz_chicago)
                gap_end_chi = gap_end_utc.tz_convert(tz_chicago)
                
                is_gap_rth = run_is_rth[r_idx]
                rth_eth = "RTH" if is_gap_rth else "ETH"
                
                glob_idx_start = np.searchsorted(native_ts, gap_start_utc, side='left')
                prev_native = native_ts[glob_idx_start - 1] if glob_idx_start > 0 else pd.NaT
                
                glob_idx_end = np.searchsorted(native_ts, gap_end_utc, side='right')
                next_native = native_ts[glob_idx_end] if glob_idx_end < len(native_ts) else pd.NaT
                
                # Fetch prev close and next open prices if available
                # But wait, this task says:
                # `previous_close`, `next_open`
                # Can we retrieve the previous close and next open prices from the raw file?
                # We can just look up native_ts in the parquet if we want, or leave it empty/nan.
                # Let's check how to load them. Since we have native_df (which is keyed by ts_event),
                # we can fetch native_df.loc[prev_native, 'close'] and native_df.loc[next_native, 'open']!
                # Let's do that!
                try:
                    prev_close = float(native_df.loc[prev_native, 'close']) if pd.notna(prev_native) else np.nan
                except Exception:
                    prev_close = np.nan
                    
                try:
                    next_open = float(native_df.loc[next_native, 'open']) if pd.notna(next_native) else np.nan
                except Exception:
                    next_open = np.nan
                
                unexplained_gaps_over_30s.append({
                    'year': session_date.year,
                    'start_utc': gap_start_utc,
                    'end_utc': gap_end_utc,
                    'start_chicago': gap_start_chi,
                    'end_chicago': gap_end_chi,
                    'missing_seconds': r_len,
                    'RTH_or_ETH': rth_eth,
                    'previous_native_timestamp': prev_native,
                    'next_native_timestamp': next_native,
                    'previous_close': prev_close,
                    'next_open': next_open,
                    'calendar_session_open': start,
                    'calendar_session_close': end
                })

print(f"Processed 2016 in {time.time() - t_gen_start:.2f}s", flush=True)
print(f"Expected seconds: {total_expected_seconds:,}")
print(f"Missing seconds:  {total_missing_seconds:,}")
print(f"Expected RTH:     {expected_rth_seconds:,}")
print(f"Expected ETH:     {expected_eth_seconds:,}")
print(f"Missing RTH:      {missing_rth_seconds:,}")
print(f"Missing ETH:      {missing_eth_seconds:,}")
print(f"Number of gaps:   {len(all_lengths_all):,}", flush=True)
print(f"Gaps >30s:        {len(unexplained_gaps_over_30s):,}", flush=True)
