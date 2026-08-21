import pandas_market_calendars as mcal
import pandas as pd

cal = mcal.get_calendar('CME_Equity')

# Check schedule for Dec 31, 2018
sch = cal.schedule(start_date='2018-12-28', end_date='2019-01-02')
print("Schedule around Dec 31, 2018:")
print(sch)
