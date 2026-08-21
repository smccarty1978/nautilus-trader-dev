import pandas_market_calendars as mcal
import pandas as pd

cal = mcal.get_calendar('CME_Equity')
# Thanksgiving 2024 (2024-11-28)
# Christmas 2024 (2024-12-25)
for holiday_start, holiday_end in [('2024-11-27', '2024-11-29'), ('2024-12-24', '2024-12-26')]:
    print(f"\n--- Period: {holiday_start} to {holiday_end} ---")
    schedule = cal.schedule(start_date=holiday_start, end_date=holiday_end)
    print(schedule)
