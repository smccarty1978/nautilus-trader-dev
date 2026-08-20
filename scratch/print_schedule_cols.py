import pandas_market_calendars as mcal
import pandas as pd

cal1 = mcal.get_calendar('CME_Equity')
schedule1 = cal1.schedule(start_date='2024-09-02', end_date='2024-09-06')
print("CME_Equity schedule columns:", list(schedule1.columns))
print(schedule1)

cal2 = mcal.get_calendar('CME Globex Equity')
schedule2 = cal2.schedule(start_date='2024-09-02', end_date='2024-09-06')
print("CME Globex Equity schedule columns:", list(schedule2.columns))
print(schedule2)
