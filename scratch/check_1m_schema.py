import pyarrow.parquet as pq

f = r"C:\Users\Scott McCarty\Projects\Nautilus Trader\data\catalog\legacy\NQ_multi_year\data\bar\NQ.XCME-1-MINUTE-LAST-EXTERNAL\2016-01-03T23-01-00-000000000Z_2026-04-16T00-00-00-000000000Z.parquet"
pf = pq.ParquetFile(f)
print(pf.schema)
df = pf.read_row_group(0).to_pandas()
print(df.head(2))
