import pandas as pd
import pyarrow.parquet as pq
import pyarrow as pa
import time

p = "data/raw/NQ_v0_mbp1_2026_01.parquet"

# Let's read the schema to see the exact type of ts_recv
pf = pq.ParquetFile(p)
print("Schema names:", pf.schema.names)

# Define a 10-second window in UTC on Jan 2, 2026
# Let's find a valid time from row group stats: e.g. 2026-01-02 00:20:00
start_ts = pd.Timestamp("2026-01-02 00:20:00", tz="UTC")
end_ts = pd.Timestamp("2026-01-02 00:20:10", tz="UTC")

print(f"\nFiltering {p} between {start_ts} and {end_ts}...")
t0 = time.time()
try:
    # Use PyArrow filters on load
    table = pq.read_table(
        p,
        filters=[
            ("ts_recv", ">=", pa.scalar(start_ts.value, pa.int64())),
            ("ts_recv", "<=", pa.scalar(end_ts.value, pa.int64()))
        ]
    )
    df = table.to_pandas()
    t1 = time.time()
    print(f"Loaded {len(df)} rows in {t1 - t0:.2f} seconds!")
    if len(df) > 0:
        print(df[["ts_event", "bid_px_00", "ask_px_00"]].head(5))
except Exception as e:
    print("Failed to filter on ts_recv as int64:", e)
    
    # Let's try standard timestamp filters
    try:
        t0 = time.time()
        table = pq.read_table(
            p,
            filters=[
                ("ts_recv", ">=", pa.scalar(start_ts.to_pydatetime())),
                ("ts_recv", "<=", pa.scalar(end_ts.to_pydatetime()))
            ]
        )
        df = table.to_pandas()
        t1 = time.time()
        print(f"Loaded {len(df)} rows with datetime filters in {t1 - t0:.2f} seconds!")
        if len(df) > 0:
            print(df[["ts_event", "bid_px_00", "ask_px_00"]].head(5))
    except Exception as e2:
        print("Failed to filter with datetime filters:", e2)
