import pandas_market_calendars as mcal
import pandas as pd

for name in ['CME_Equity', 'CME Globex Equity']:
    try:
        cal = mcal.get_calendar(name)
        print(f"\n--- {name} ---")
        print(f"Timezone: {cal.tz}")
        schedule = cal.schedule(start_date='2024-09-02', end_date='2024-09-06')
        print(schedule)
    except Exception as e:
        print(f"Error {name}: {e}")
