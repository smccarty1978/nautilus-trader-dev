import pandas as pd
import pyarrow.parquet as pq

p = "data/raw/NQ_v0_mbp1_2026_01.parquet"
pf = pq.ParquetFile(p)

print("Checking first 10 row groups statistics:")
for i in range(10):
    meta = pf.metadata.row_group(i)
    # Let's find ts_event or ts_recv column statistics
    ts_event_col = -1
    ts_recv_col = -1
    for col_idx in range(meta.num_columns):
        col_meta = meta.column(col_idx)
        path_in_schema = col_meta.path_in_schema
        if path_in_schema == "ts_event":
            ts_event_col = col_idx
        elif path_in_schema == "ts_recv":
            ts_recv_col = col_idx
            
    # Print stats if available
    event_stats = meta.column(ts_event_col).statistics if ts_event_col != -1 else None
    recv_stats = meta.column(ts_recv_col).statistics if ts_recv_col != -1 else None
    
    event_min = pd.to_datetime(event_stats.min, unit='ns', utc=True) if event_stats else None
    event_max = pd.to_datetime(event_stats.max, unit='ns', utc=True) if event_stats else None
    recv_min = pd.to_datetime(recv_stats.min, unit='ns', utc=True) if recv_stats else None
    recv_max = pd.to_datetime(recv_stats.max, unit='ns', utc=True) if recv_stats else None
    
    print(f"Row group {i}:")
    print(f"  ts_event range: {event_min} to {event_max}")
    print(f"  ts_recv range : {recv_min} to {recv_max}")
