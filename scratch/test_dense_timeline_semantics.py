import datetime
import pandas as pd
import pandas_market_calendars as mcal

def has_expected_open_second(start_ns: int, end_ns: int) -> bool:
    dt_start = pd.to_datetime(start_ns, unit='ns', utc=True)
    dt_end = pd.to_datetime(end_ns, unit='ns', utc=True)
    
    calendar = mcal.get_calendar("CME_Equity")
    schedule = calendar.schedule(
        start_date=(dt_start.date() - datetime.timedelta(days=1)).isoformat(),
        end_date=(dt_end.date() + datetime.timedelta(days=1)).isoformat(),
        market_times="all"
    )
    
    for session_day, row in schedule.iterrows():
        open_ns = int(row.market_open.value)
        close_ns = int(row.market_close.value)
        
        intervals = [(open_ns, close_ns - 1_000_000_000)]
        if session_day.date() <= datetime.date(2021, 6, 25) and "break_start" in schedule.columns:
            break_start = int(row.break_start.value)
            break_end = int(row.break_end.value)
            if open_ns < break_start < break_end < close_ns:
                intervals = [(open_ns, break_start - 1_000_000_000), (break_end, close_ns - 1_000_000_000)]
                
        for s_ns, e_ns in intervals:
            overlap_start = max(s_ns, start_ns)
            overlap_end = min(e_ns, end_ns)
            if overlap_start <= overlap_end:
                return True
    return False

# Holiday: Christmas Day 2024
t_thu = int(pd.Timestamp("2024-12-24 17:59:59", tz="UTC").value)
t_reopen = int(pd.Timestamp("2024-12-25 23:00:00", tz="UTC").value)
print("Holiday test (expected: False):", has_expected_open_second(t_thu + 1_000_000_000, t_reopen - 1_000_000_000))
