import pyarrow.parquet as pq
import pandas as pd
from pathlib import Path
import pytz

CT = pytz.timezone("America/Chicago")

# Target interval: 2024-01-05 10:00:00 to 10:00:59 CT
# In UTC: 2024-01-05 16:00:00 to 16:00:59 UTC
dt_start_utc = pd.Timestamp("2024-01-05 16:00:00", tz="UTC")
dt_end_utc = pd.Timestamp("2024-01-05 16:01:00", tz="UTC")

ts_start_ns = dt_start_utc.value
ts_end_ns = dt_end_utc.value

print("=" * 75)
print("CONCRETE INTERVAL FORENSIC COMPARISON")
print(f"Interval: 10:00:00 CT -> 10:00:59.999 CT (16:00:00 UTC -> 16:00:59.999 UTC)")
print("=" * 75)

# 1. Raw Databento 1s file
raw_file = Path("data/raw/NQ_v0_1s_2024.parquet")
raw_pf = pq.ParquetFile(raw_file)

# Read 1s rows in window
raw_df = pd.read_parquet(raw_file, filters=[
    ("ts_event", ">=", dt_start_utc),
    ("ts_event", "<=", dt_end_utc + pd.Timedelta(seconds=5))
])

print(f"\n1. RAW DATABENTO 1s FILE ({raw_file.name}):")
print(f"First 3 records in interval:")
print(raw_df.head(3)[["open", "high", "low", "close", "volume"]])
print(f"Record at 16:00:00 UTC (10:00:00 CT):")
print(f"  Index (ts_event): {raw_df.index[0]} (Semantic: Interval OPEN [10:00:00, 10:00:01) CT)")
print(f"  Causal availability time of this 1s bar: 10:00:01 CT (16:00:01 UTC)")

# 2. Resampled 1m bar (using canonical resample)
# Window [16:00:00, 16:01:00) with closed='left'
resampled_1m_left = raw_df.loc[dt_start_utc:dt_end_utc - pd.Timedelta(nanoseconds=1)].resample("1min", label="left", closed="left").agg({
    "open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"
})
resampled_1m_right = raw_df.loc[dt_start_utc:dt_end_utc - pd.Timedelta(nanoseconds=1)].resample("1min", label="right", closed="left").agg({
    "open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"
})

print(f"\n2. RESAMPLED 1m BAR FROM 1s:")
print(f"  With label='left' (open-stamped):  Index={resampled_1m_left.index[0]} (10:00:00 CT)")
print(f"  With label='right' (close-stamped): Index={resampled_1m_right.index[0]} (10:01:00 CT)")
print(f"  OHLCV: O={resampled_1m_left.iloc[0]['open']} H={resampled_1m_left.iloc[0]['high']} L={resampled_1m_left.iloc[0]['low']} C={resampled_1m_left.iloc[0]['close']} V={resampled_1m_left.iloc[0]['volume']}")

# 3. NT Catalog 1s bar
cat_1s_file = list(Path("data/catalog/NQ_v0_2020_2026/data/bar/NQ.XCME-1-SECOND-LAST-EXTERNAL").glob("*.parquet"))[0]
cat_1s_df = pd.read_parquet(cat_1s_file, filters=[
    ("ts_init", ">=", ts_start_ns),
    ("ts_init", "<=", ts_end_ns)
])

print(f"\n3. NT CATALOG 1s BAR ({cat_1s_file.name}):")
if len(cat_1s_df) > 0:
    row0 = cat_1s_df.iloc[0]
    print(f"  First bar in window:")
    print(f"    ts_event = {row0['ts_event']} ({pd.to_datetime(row0['ts_event'], unit='ns', utc=True)}) -> [OPEN time]")
    print(f"    ts_init  = {row0['ts_init']} ({pd.to_datetime(row0['ts_init'], unit='ns', utc=True)}) -> [CLOSE time / Event Loop Dispatch]")
    print(f"    Delta    = {row0['ts_init'] - row0['ts_event']} ns (+1.0s)")

# 4. NT Catalog 1m bar
cat_1m_file = list(Path("data/catalog/NQ_v0_2020_2026/data/bar/NQ.XCME-1-MINUTE-LAST-EXTERNAL").glob("*.parquet"))[0]
cat_1m_df = pd.read_parquet(cat_1m_file, filters=[
    ("ts_init", ">=", ts_start_ns),
    ("ts_init", "<=", ts_end_ns + 60_000_000_000)
])

print(f"\n4. NT CATALOG 1m BAR ({cat_1m_file.name}):")
if len(cat_1m_df) > 0:
    for idx, r in cat_1m_df.iterrows():
        dt_e = pd.to_datetime(r['ts_event'], unit='ns', utc=True)
        dt_i = pd.to_datetime(r['ts_init'], unit='ns', utc=True)
        if dt_e == dt_start_utc or dt_i == dt_end_utc:
            print(f"  10:00:00-10:01:00 CT Bar:")
            print(f"    ts_event = {r['ts_event']} ({dt_e}) -> [OPEN time]")
            print(f"    ts_init  = {r['ts_init']} ({dt_i}) -> [CLOSE time / Event Loop Dispatch]")
            print(f"    Delta    = {r['ts_init'] - r['ts_event']} ns (+60.0s)")
