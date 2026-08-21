import pandas_market_calendars as mcal
import pandas as pd

cal1 = mcal.get_calendar('CME_Equity')
schedule1 = cal1.schedule(start_date='2024-09-03', end_date='2024-09-05')
print(schedule1.to_dict('records'))
