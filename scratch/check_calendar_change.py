import pandas_market_calendars as mcal
import pandas as pd

cal = mcal.get_calendar('CME_Equity')
schedule = cal.schedule(start_date='2021-06-21', end_date='2021-07-02')
print(schedule.to_dict('records'))
