import pandas_market_calendars as mcal
import pandas as pd

# List available calendar names
print("Available calendars:")
print(mcal.get_calendar_names())

try:
    cme_cal = mcal.get_calendar('CMEGlobex_Equity')
    print("Successfully retrieved CMEGlobex_Equity")
except Exception as e:
    print(f"Error CMEGlobex_Equity: {e}")

try:
    cme_cal = mcal.get_calendar('CME_Equity')
    print("Successfully retrieved CME_Equity")
except Exception as e:
    print(f"Error CME_Equity: {e}")

try:
    cme_cal = mcal.get_calendar('CME')
    print("Successfully retrieved CME")
except Exception as e:
    print(f"Error CME: {e}")
