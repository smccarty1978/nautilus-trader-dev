import pandas_market_calendars as mcal
import pandas as pd

cal = mcal.get_calendar('CME_Equity')
schedule = cal.schedule(start_date='2024-11-25', end_date='2024-11-29')
print(schedule.to_dict('records'))
