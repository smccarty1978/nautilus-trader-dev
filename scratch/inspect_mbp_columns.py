import pandas as pd
import pyarrow.parquet as pq

p = "data/raw/NQ_v0_mbp1_2026_01.parquet"
pf = pq.ParquetFile(p)
print("Parquet schema columns:")
print(pf.schema.names)
print("\nFirst row of data:")
df_head = pf.read_row_group(0).to_pandas().head(1)
print(df_head)
