import os
import time
import pandas as pd
import numpy as np
import pytz

def main():
    impact_csv = r"C:\Users\Scott McCarty\Projects\Nautilus Trader\eth_gap_1m_impact.csv"
    df_impact = pd.read_csv(impact_csv)
    
    # Filter for COMPLETE_EMPTY_MINUTE
    df_empty = df_impact[df_impact['reconciliation_status'] == 'COMPLETE_EMPTY_MINUTE'].copy()
    print(f"Loaded {len(df_empty)} COMPLETE_EMPTY_MINUTE records.")

    # Load 1m reference bars
    f_early_1m = r"C:\Users\Scott McCarty\Projects\Nautilus Trader\data\catalog\legacy\NQ_multi_year\data\bar\NQ.XCME-1-MINUTE-LAST-EXTERNAL\2016-01-03T23-01-00-000000000Z_2026-04-16T00-00-00-000000000Z.parquet"
    f_recent_1m = r"C:\Users\Scott McCarty\Projects\Nautilus Trader\data\catalog\NQ_v0_2020_2026\data\bar\NQ.XCME-1-MINUTE-LAST-EXTERNAL\2020-01-01T23-01-00-000000000Z_2026-04-30T00-00-00-000000000Z.parquet"
    
    print("Loading 1m reference bars...")
    df_1m_early = pd.read_parquet(f_early_1m)
    df_1m_recent = pd.read_parquet(f_recent_1m)
    for col in ['open', 'high', 'low', 'close', 'volume']:
        df_1m_early[col] = np.frombuffer(b''.join(df_1m_early[col].values), dtype=np.int64) / 10**9
        df_1m_recent[col] = np.frombuffer(b''.join(df_1m_recent[col].values), dtype=np.int64) / 10**9
    df_1m_early.index = pd.to_datetime(df_1m_early['ts_event'], unit='ns', utc=True)
    df_1m_recent.index = pd.to_datetime(df_1m_recent['ts_event'], unit='ns', utc=True)
    df_1m = pd.concat([df_1m_early, df_1m_recent])
    df_1m = df_1m[~df_1m.index.duplicated(keep='first')]
    print(f"Loaded {len(df_1m):,} reference bars.")

    # Load gaps to check classification
    df_gaps = pd.read_csv("eth_gap_reclassification.csv")

    results = []
    no_ref_count = 0
    flat_zero_count = 0
    has_trades_count = 0
    
    tz_chicago = pytz.timezone('America/Chicago')

    for idx, row in df_empty.iterrows():
        min_utc = pd.Timestamp(row['minute_utc'])
        
        # Check if in reference 1m
        if min_utc in df_1m.index:
            ref_row = df_1m.loc[min_utc]
            if isinstance(ref_row, pd.DataFrame):
                ref_row = ref_row.iloc[0]
            
            ref_v = float(ref_row['volume'])
            ref_o = float(ref_row['open'])
            ref_h = float(ref_row['high'])
            ref_l = float(ref_row['low'])
            ref_c = float(ref_row['close'])
            
            is_flat_zero = (ref_v == 0.0) and (ref_o == ref_h == ref_l == ref_c)
            if is_flat_zero:
                flat_zero_count += 1
                status = "REFERENCE_FLAT_ZERO_VOLUME"
            else:
                has_trades_count += 1
                status = "REFERENCE_HAS_TRADES"
                
                # Fetch more details for REFERENCE_HAS_TRADES
                gap_idx = row['gap_index']
                gap_row = df_gaps[df_gaps['original_index'] == gap_idx].iloc[0]
                
                min_chi = min_utc.tz_convert(tz_chicago)
                
                results.append({
                    'year': int(row['year']),
                    'timestamp_utc': min_utc.isoformat(),
                    'timestamp_ct': min_chi.isoformat(),
                    'ref_o': ref_o,
                    'ref_h': ref_h,
                    'ref_l': ref_l,
                    'ref_c': ref_c,
                    'ref_v': ref_v,
                    'prev_native_ts': gap_row['previous_native_timestamp'],
                    'next_native_ts': gap_row['next_native_timestamp'],
                    'gap_classification': gap_row['classification'],
                    'gap_severity': gap_row['severity']
                })
        else:
            no_ref_count += 1
            status = "NO_REFERENCE_1M"

    print("\n--- RESULTS ---")
    print(f"COMPLETE EMPTY MINUTES: {len(df_empty)}")
    print(f"NO_REFERENCE_1M: {no_ref_count}")
    print(f"REFERENCE_FLAT_ZERO_VOLUME: {flat_zero_count}")
    print(f"REFERENCE_HAS_TRADES: {has_trades_count}")
    
    if has_trades_count > 0:
        df_has_trades = pd.DataFrame(results)
        print("\nReference Has Trades Detailed:")
        print(df_has_trades)
        
        # Split by epoch
        df_early_ht = df_has_trades[df_has_trades['year'] <= 2020]
        df_recent_ht = df_has_trades[df_has_trades['year'] >= 2021]
        print(f"\n2016-2020 REFERENCE_HAS_TRADES: {len(df_early_ht)}")
        print(f"2021-2026 REFERENCE_HAS_TRADES: {len(df_recent_ht)}")
        
        max_v = df_has_trades['ref_v'].max()
        print(f"Maximum reference volume: {max_v}")
        print("Affected timestamps:", df_has_trades['timestamp_utc'].tolist())
    else:
        print("\n2016-2020 REFERENCE_HAS_TRADES: 0")
        print("2021-2026 REFERENCE_HAS_TRADES: 0")

if __name__ == "__main__":
    main()
