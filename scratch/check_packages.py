import sys
try:
    import pandas_market_calendars as mcal
    print(f"pandas_market_calendars version: {mcal.__version__}")
except ImportError:
    print("pandas-market-calendars not installed")
