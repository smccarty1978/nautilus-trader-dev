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
    t_start = time.time()
    cal = mcal.get_calendar('CME_Equity')
    tz_chicago = pytz.timezone('America/Chicago')
    mcal_version = mcal.__version__

    raw_dir = r"C:\Users\Scott McCarty\Projects\Nautilus Trader\data\raw"
    pattern = os.path.join(raw_dir, "NQ_v0_1s_*.parquet")
    files = sorted(glob.glob(pattern))

    print(f"Found {len(files)} NQ 1s files for audit.")

    # We need a reproducible calendar mapping
    symbol_calendar_map = {
        "NQ": "CME_Equity",
        "MNQ": "CME_Equity",
        "ES": "CME_Equity",
        "MES": "CME_Equity"
    }
    resolved_calendar_name = symbol_calendar_map.get("NQ")
    print(f"NQ mapped to calendar: {resolved_calendar_name}")

    # Accumulators for overall metrics
    overall_expected_seconds = 0
    overall_missing_seconds = 0
    overall_expected_rth = 0
    overall_expected_eth = 0
    overall_missing_rth = 0
    overall_missing_eth = 0
    overall_native_rows = 0
    overall_distinct_runs = 0

    # Year-by-year dictionary for reporting
    year_reports = {}

    # Bincount accumulators for quantiles (up to 100,000 seconds)
    max_bin_size = 100000
    overall_bincount = np.zeros(max_bin_size, dtype=np.int64)
    rth_bincount = np.zeros(max_bin_size, dtype=np.int64)
    eth_bincount = np.zeros(max_bin_size, dtype=np.int64)
    year_bincounts = {}

    # Buckets definition
    bucket_keys = ['1s', '2s', '3-5s', '6-10s', '11-30s', '>30s']
    
    overall_buckets = {b: 0 for b in bucket_keys}
    rth_buckets = {b: 0 for b in bucket_keys}
    eth_buckets = {b: 0 for b in bucket_keys}
    year_buckets = {}

    # Gaps list for CSV exports
    unexplained_gaps = []
    calendar_reviews = []

    longest_gap_overall = None # will store dict with start, duration, rth/eth

    # Preflight calendar validation
    print("Performing calendar validation checks...")
    validation_status = "PASS"
    try:
        # Check standard Wednesday
        sch_normal = cal.schedule(start_date='2024-09-04', end_date='2024-09-04')
        assert len(sch_normal) == 1
        row = sch_normal.iloc[0]
        assert row['market_open'].tz_convert(tz_chicago).time() == pd.Timestamp('17:00:00').time()
        assert row['market_close'].tz_convert(tz_chicago).time() == pd.Timestamp('16:00:00').time()
        assert row['break_start'].tz_convert(tz_chicago).time() == pd.Timestamp('15:15:00').time()
        
        # Check Christmas 2024
        sch_xmas = cal.schedule(start_date='2024-12-25', end_date='2024-12-25')
        assert len(sch_xmas) == 0
        
        print("Calendar validation: PASS")
    except Exception as e:
        print(f"Calendar validation: FAIL ({e})")
        validation_status = "FAIL"

    for f in files:
        f_start_time = time.time()
        filename = os.path.basename(f)
        year_str = filename.split('_')[3].split('.')[0]
        if 'ytd' in year_str:
            year_val = 2026
        else:
            year_val = int(year_str)

        print(f"\nProcessing {filename} (Year {year_val})...", flush=True)

        pf = pq.ParquetFile(f)
        file_native_rows = pf.metadata.num_rows
        overall_native_rows += file_native_rows

        # Read only index ts_event
        table = pq.read_table(f, columns=['ts_event'])
        native_df = table.to_pandas()
        native_ts = native_df.index.unique().sort_values()

        # Generate schedule for this year
        # Note: raw files cover 2016-01-03 to 2026-04-29
        # So we restrict start/end date queries to the actual range of the year
        if year_val == 2016:
            start_date_q = '2016-01-03'
            end_date_q = '2016-12-31'
        elif year_val == 2026:
            start_date_q = '2026-01-01'
            end_date_q = '2026-05-01'
        else:
            start_date_q = f'{year_val}-01-01'
            end_date_q = f'{year_val}-12-31'

        schedule = cal.schedule(start_date=start_date_q, end_date=end_date_q)
        print(f"  Schedule rows: {len(schedule)}", flush=True)

        # Initialize year accumulators
        year_expected_seconds = 0
        year_missing_seconds = 0
        year_expected_rth = 0
        year_expected_eth = 0
        year_missing_rth = 0
        year_missing_eth = 0
        year_distinct_runs = 0
        
        y_bincount = np.zeros(max_bin_size, dtype=np.int64)
        y_buckets = {b: 0 for b in bucket_keys}

        # Cache timezone offset calculations
        offset_cache = {}

        for idx, row in schedule.iterrows():
            session_date = idx.date()
            open_val = row['market_open']
            close_val = row['market_close']
            break_start = row.get('break_start', pd.NaT)
            break_end = row.get('break_end', pd.NaT)

            # Determine intervals
            intervals = []
            has_breaks = (pd.notna(break_start) and pd.notna(break_end) and 
                          'break_start' in row and 'break_end' in row)
            
            if has_breaks:
                end1 = break_start if break_start > open_val else close_val
                if open_val < end1:
                    intervals.append((open_val, end1))
                if break_end < close_val:
                    intervals.append((break_end, close_val))
            else:
                if open_val < close_val:
                    intervals.append((open_val, close_val))

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

                sub_expected_count = len(expected_sub)
                sub_missing_count = missing_mask.sum()

                # Classification of RTH / ETH
                # Timezone offset cache
                date_key = start.floor('D')
                if date_key not in offset_cache:
                    offset_cache[date_key] = int(start.tz_convert(tz_chicago).utcoffset().total_seconds())
                offset_sec = offset_cache[date_key]

                expected_sec = expected_sub.values.astype('int64') // 10**9
                chicago_sec = (expected_sec + offset_sec) % 86400

                rth_start_sec = 8 * 3600 + 30 * 60
                rth_end_sec = 15 * 3600 + 15 * 60

                is_rth_mask = (chicago_sec >= rth_start_sec) & (chicago_sec < rth_end_sec)

                sub_expected_rth = is_rth_mask.sum()
                sub_expected_eth = sub_expected_count - sub_expected_rth

                sub_missing_rth = (missing_mask & is_rth_mask).sum()
                sub_missing_eth = sub_missing_count - sub_missing_rth

                # Update daily metrics
                year_expected_seconds += sub_expected_count
                year_missing_seconds += sub_missing_count
                year_expected_rth += sub_expected_rth
                year_expected_eth += sub_expected_eth
                year_missing_rth += sub_missing_rth
                year_missing_eth += sub_missing_eth

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

                    # Count gap runs
                    year_distinct_runs += len(run_lengths)

                    # Update bincounts and buckets
                    # clip run lengths to avoid out of bounds
                    clipped_lengths = np.clip(run_lengths, 0, max_bin_size - 1)
                    for r_len, r_rth in zip(clipped_lengths, run_is_rth):
                        overall_bincount[r_len] += 1
                        y_bincount[r_len] += 1
                        if r_rth:
                            rth_bincount[r_len] += 1
                        else:
                            eth_bincount[r_len] += 1

                    # Count buckets function
                    def update_buckets(lengths, buckets_dict):
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

                    update_buckets(run_lengths, overall_buckets)
                    update_buckets(run_lengths, y_buckets)
                    update_buckets(run_lengths[run_is_rth], rth_buckets)
                    update_buckets(run_lengths[~run_is_rth], eth_buckets)

                    # Check gaps > 30s
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

                        # Fetch close/open prices
                        try:
                            prev_close = float(native_df.loc[prev_native, 'close']) if pd.notna(prev_native) else np.nan
                        except Exception:
                            prev_close = np.nan

                        try:
                            next_open = float(native_df.loc[next_native, 'open']) if pd.notna(next_native) else np.nan
                        except Exception:
                            next_open = np.nan

                        gap_rec = {
                            'year': year_val,
                            'start_utc': gap_start_utc.isoformat(),
                            'end_utc': gap_end_utc.isoformat(),
                            'start_chicago': gap_start_chi.isoformat(),
                            'end_chicago': gap_end_chi.isoformat(),
                            'missing_seconds': int(r_len),
                            'RTH_or_ETH': rth_eth,
                            'previous_native_timestamp': prev_native.isoformat() if pd.notna(prev_native) else 'NaT',
                            'next_native_timestamp': next_native.isoformat() if pd.notna(next_native) else 'NaT',
                            'previous_close': prev_close,
                            'next_open': next_open,
                            'calendar_session_open': start.isoformat(),
                            'calendar_session_close': end.isoformat()
                        }

                        # Check if gap touches boundaries
                        # touches open boundary
                        touches_open = (gap_start_utc == start)
                        # touches close boundary
                        touches_close = (gap_end_utc + pd.Timedelta(seconds=1) == end)

                        if touches_open or touches_close:
                            calendar_reviews.append(gap_rec)
                        else:
                            unexplained_gaps.append(gap_rec)

                        # Check if this is the longest gap overall
                        if longest_gap_overall is None or r_len > longest_gap_overall['missing_seconds']:
                            longest_gap_overall = {
                                'timestamp': gap_start_utc.isoformat(),
                                'timestamp_chicago': gap_start_chi.isoformat(),
                                'missing_seconds': int(r_len),
                                'RTH_or_ETH': rth_eth
                            }

        # Calculate quantiles for the year from y_bincount
        def get_quantiles(bincount):
            q_vals = [0.5, 0.9, 0.99]
            total_gap_events = bincount.sum()
            if total_gap_events == 0:
                return 0.0, 0.0, 0.0, 0
            cumsum = np.cumsum(bincount)
            results = []
            for q in q_vals:
                target = q * total_gap_events
                val = np.searchsorted(cumsum, target)
                results.append(float(val))
            max_val = int(np.max(np.where(bincount > 0)[0]))
            return results[0], results[1], results[2], max_val

        y_med, y_p90, y_p99, y_max = get_quantiles(y_bincount)

        # Record report for the year
        year_reports[year_val] = {
            'expected_seconds': year_expected_seconds,
            'native_rows': year_expected_seconds - year_missing_seconds,
            'absent_seconds': year_missing_seconds,
            'absent_pct': (year_missing_seconds / year_expected_seconds * 100.0) if year_expected_seconds > 0 else 0.0,
            'distinct_gap_runs': year_distinct_runs,
            'median_gap_length': y_med,
            'p90_gap_length': y_p90,
            'p99_gap_length': y_p99,
            'max_gap_length': y_max,
            **y_buckets
        }

        # Accumulate overall stats
        overall_expected_seconds += year_expected_seconds
        overall_missing_seconds += year_missing_seconds
        overall_expected_rth += year_expected_rth
        overall_expected_eth += year_expected_eth
        overall_missing_rth += year_missing_rth
        overall_missing_eth += year_missing_eth
        overall_distinct_runs += year_distinct_runs

        year_bincounts[year_val] = y_bincount
        year_buckets[year_val] = y_buckets

        print(f"  Done in {time.time() - f_start_time:.1f}s. Expected: {year_expected_seconds:,}, Missing: {year_missing_seconds:,}", flush=True)

    # Compute overall quantiles
    def get_quantiles_global(bincount):
        q_vals = [0.5, 0.9, 0.99]
        total_gap_events = bincount.sum()
        if total_gap_events == 0:
            return 0.0, 0.0, 0.0, 0
        cumsum = np.cumsum(bincount)
        results = []
        for q in q_vals:
            target = q * total_gap_events
            val = np.searchsorted(cumsum, target)
            results.append(float(val))
        max_val = int(np.max(np.where(bincount > 0)[0]))
        return results[0], results[1], results[2], max_val

    overall_med, overall_p90, overall_p99, overall_max = get_quantiles_global(overall_bincount)
    rth_med, rth_p90, rth_p99, rth_max = get_quantiles_global(rth_bincount)
    eth_med, eth_p90, eth_p99, eth_max = get_quantiles_global(eth_bincount)

    # Compile the final summary table as a list of dicts
    summary_records = []
    
    # 1. Overall
    summary_records.append({
        'segment': 'Overall',
        'expected_seconds': overall_expected_seconds,
        'native_rows': overall_expected_seconds - overall_missing_seconds,
        'absent_seconds': overall_missing_seconds,
        'absent_pct': (overall_missing_seconds / overall_expected_seconds * 100.0) if overall_expected_seconds > 0 else 0.0,
        'distinct_gap_runs': overall_distinct_runs,
        'median_gap_length': overall_med,
        'p90_gap_length': overall_p90,
        'p99_gap_length': overall_p99,
        'max_gap_length': overall_max,
        **overall_buckets
    })

    # 2. RTH
    rth_count_runs = rth_bincount.sum()
    summary_records.append({
        'segment': 'RTH',
        'expected_seconds': overall_expected_rth,
        'native_rows': overall_expected_rth - overall_missing_rth,
        'absent_seconds': overall_missing_rth,
        'absent_pct': (overall_missing_rth / overall_expected_rth * 100.0) if overall_expected_rth > 0 else 0.0,
        'distinct_gap_runs': int(rth_count_runs),
        'median_gap_length': rth_med,
        'p90_gap_length': rth_p90,
        'p99_gap_length': rth_p99,
        'max_gap_length': rth_max,
        **rth_buckets
    })

    # 3. ETH
    eth_count_runs = eth_bincount.sum()
    summary_records.append({
        'segment': 'ETH',
        'expected_seconds': overall_expected_eth,
        'native_rows': overall_expected_eth - overall_missing_eth,
        'absent_seconds': overall_missing_eth,
        'absent_pct': (overall_missing_eth / overall_expected_eth * 100.0) if overall_expected_eth > 0 else 0.0,
        'distinct_gap_runs': int(eth_count_runs),
        'median_gap_length': eth_med,
        'p90_gap_length': eth_p90,
        'p99_gap_length': eth_p99,
        'max_gap_length': eth_max,
        **eth_buckets
    })

    # 4. By Year
    for yr in sorted(year_reports.keys()):
        yr_data = year_reports[yr]
        summary_records.append({
            'segment': f'Year_{yr}',
            'expected_seconds': yr_data['expected_seconds'],
            'native_rows': yr_data['native_rows'],
            'absent_seconds': yr_data['absent_seconds'],
            'absent_pct': yr_data['absent_pct'],
            'distinct_gap_runs': yr_data['distinct_gap_runs'],
            'median_gap_length': yr_data['median_gap_length'],
            'p90_gap_length': yr_data['p90_gap_length'],
            'p99_gap_length': yr_data['p99_gap_length'],
            'max_gap_length': yr_data['max_gap_length'],
            '1s': yr_data['1s'],
            '2s': yr_data['2s'],
            '3-5s': yr_data['3-5s'],
            '6-10s': yr_data['6-10s'],
            '11-30s': yr_data['11-30s'],
            '>30s': yr_data['>30s']
        })

    # Convert to DataFrames
    df_summary = pd.DataFrame(summary_records)
    df_unexplained = pd.DataFrame(unexplained_gaps)
    df_calendar_review = pd.DataFrame(calendar_reviews)

    # Sort unexplained gaps longest first
    if not df_unexplained.empty:
        df_unexplained = df_unexplained.sort_values(by='missing_seconds', ascending=False)
    if not df_calendar_review.empty:
        df_calendar_review = df_calendar_review.sort_values(by='missing_seconds', ascending=False)

    # Save to CSV and JSON
    summary_csv = "gap_audit_summary.csv"
    summary_json = "gap_audit_summary.json"
    unexplained_csv = "unexplained_gaps_over_30s.csv"
    calendar_review_csv = "calendar_review_required.csv"

    df_summary.to_csv(summary_csv, index=False)
    
    # Save json summary formatted cleanly
    def make_json_serializable(obj):
        if isinstance(obj, dict):
            return {k: make_json_serializable(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [make_json_serializable(x) for x in obj]
        elif isinstance(obj, (np.integer, np.int64)):
            return int(obj)
        elif isinstance(obj, (np.floating, np.float64)):
            return float(obj)
        elif isinstance(obj, np.ndarray):
            return make_json_serializable(obj.tolist())
        else:
            return obj

    with open(summary_json, 'w') as jf:
        json.dump(make_json_serializable(summary_records), jf, indent=2)

    df_unexplained.to_csv(unexplained_csv, index=False)
    df_calendar_review.to_csv(calendar_review_csv, index=False)

    print("\n--- AUDIT COMPLETE ---")
    print(f"Artifacts written:")
    print(f"  {summary_csv}")
    print(f"  {summary_json}")
    print(f"  {unexplained_csv}")
    print(f"  {calendar_review_csv}")

    # Print final response block
    print("\n================== FINAL RESPONSE BLOCK ==================")
    print("RAW DATA")
    print(f"    files: {len(files)}")
    print(f"    years: 2016-2026")
    print(f"    native rows: {overall_native_rows:,}")
    print("")
    print("CALENDAR")
    print(f"    calendar used: {resolved_calendar_name}")
    print(f"    pandas-market-calendars version: {mcal_version}")
    print(f"    calendar validation: {validation_status}")
    print("")
    print("OVERALL")
    print(f"    expected tradable seconds: {overall_expected_seconds:,}")
    print(f"    missing seconds: {overall_missing_seconds:,}")
    print(f"    missing % of expected: {overall_missing_seconds / overall_expected_seconds * 100.0:.4f}%")
    print(f"    missing seconds / native rows: {overall_missing_seconds / overall_native_rows:.4f}")
    print(f"    distinct gap runs: {overall_distinct_runs:,}")
    print("")
    print("GAP COUNTS")
    print(f"    1 sec: {overall_buckets['1s']:,}")
    print(f"    2 sec: {overall_buckets['2s']:,}")
    print(f"    3-5 sec: {overall_buckets['3-5s']:,}")
    print(f"    6-10 sec: {overall_buckets['6-10s']:,}")
    print(f"    11-30 sec: {overall_buckets['11-30s']:,}")
    print(f"    >30 sec: {overall_buckets['>30s']:,}")
    print("")
    print("RTH")
    print(f"    expected seconds: {overall_expected_rth:,}")
    print(f"    missing seconds: {overall_missing_rth:,}")
    print(f"    missing %: {overall_missing_rth / overall_expected_rth * 100.0:.4f}%")
    print(f"    gap runs: {int(rth_count_runs):,}")
    print("")
    print("ETH")
    print(f"    expected seconds: {overall_expected_eth:,}")
    print(f"    missing seconds: {overall_missing_eth:,}")
    print(f"    missing %: {overall_missing_eth / overall_expected_eth * 100.0:.4f}%")
    print(f"    gap runs: {int(eth_count_runs):,}")
    print("")
    print("LONGEST GAP")
    if longest_gap_overall:
        print(f"    timestamp: {longest_gap_overall['timestamp']} ({longest_gap_overall['timestamp_chicago']} Chicago)")
        print(f"    duration: {longest_gap_overall['missing_seconds']} seconds")
        print(f"    RTH/ETH: {longest_gap_overall['RTH_or_ETH']}")
    else:
        print("    timestamp: N/A")
        print("    duration: 0 seconds")
        print("    RTH/ETH: N/A")
    print("")
    print("UNEXPLAINED >30 SECOND GAPS")
    print(f"    count: {len(unexplained_gaps):,}")
    print("")
    print("CALENDAR_REVIEW_REQUIRED")
    print(f"    count: {len(calendar_reviews):,}")
    print("")
    print("ARTIFACTS")
    print(f"    {os.path.abspath(summary_csv)}")
    print(f"    {os.path.abspath(summary_json)}")
    print(f"    {os.path.abspath(unexplained_csv)}")
    print(f"    {os.path.abspath(calendar_review_csv)}")
    print("")
    print("STATUS")
    print("    GAP_AUDIT_COMPLETE")
    print("==========================================================")

if __name__ == "__main__":
    main()
