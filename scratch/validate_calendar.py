import pandas_market_calendars as mcal
import pandas as pd
import pytz

cal = mcal.get_calendar('CME_Equity')
tz_chicago = pytz.timezone('America/Chicago')

def validate_date_range(start_date, end_date):
    print(f"\n--- Validation range: {start_date} to {end_date} ---")
    schedule = cal.schedule(start_date=start_date, end_date=end_date)
    for idx, row in schedule.iterrows():
        open_val = row['market_open']
        close_val = row['market_close']
        break_start = row.get('break_start', pd.NaT)
        break_end = row.get('break_end', pd.NaT)
        
        open_chi = open_val.tz_convert(tz_chicago)
        close_chi = close_val.tz_convert(tz_chicago)
        break_start_chi = break_start.tz_convert(tz_chicago) if pd.notna(break_start) else None
        break_end_chi = break_end.tz_convert(tz_chicago) if pd.notna(break_end) else None
        
        print(f"Trading Date: {idx.date()}")
        print(f"  Open (UTC):  {open_val} | (Chicago): {open_chi}")
        print(f"  Close (UTC): {close_val} | (Chicago): {close_chi}")
        if break_start_chi:
            print(f"  Break: {break_start_chi} to {break_end_chi}")
        else:
            print("  No Break")

# 1. Normal weekday
validate_date_range('2024-09-04', '2024-09-04')

# 2. Thanksgiving 2024
validate_date_range('2024-11-27', '2024-11-29')

# 3. Christmas 2024
validate_date_range('2024-12-24', '2024-12-26')

# 4. New Year's 2024-2025
validate_date_range('2024-12-31', '2025-01-02')

# 5. DST Transition Spring 2024 (March 10, 2024)
validate_date_range('2024-03-08', '2024-03-11')

# 6. DST Transition Fall 2024 (November 3, 2024)
validate_date_range('2024-11-01', '2024-11-04')
