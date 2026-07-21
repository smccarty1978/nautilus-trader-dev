import pandas as pd
import pyarrow.parquet as pq

p = "data/raw/NQ_v0_mbp1_2026_01.parquet"
pf = pq.ParquetFile(p)
print(f"Number of row groups: {pf.num_row_groups}")
print(f"Schema names: {pf.schema.names}")

# Let's read a tiny part of the first row group and inspect types
df_tiny = pf.read_row_group(0).to_pandas().head(5)
print("Tiny head index:")
print(df_tiny.index)
print("Tiny head index name:", df_tiny.index.name)
print("Tiny head columns and types:")
print(df_tiny.dtypes)
print(df_tiny[["ts_event", "bid_px_00", "ask_px_00"]].head(5))
