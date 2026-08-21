import pyarrow.parquet as pq
import glob
import os

raw_dir = r"C:\Users\Scott McCarty\Projects\Nautilus Trader\data\raw"
pattern = os.path.join(raw_dir, "NQ_v0_1s_*.parquet")
files = sorted(glob.glob(pattern))

if files:
    f = files[0]
    pf = pq.ParquetFile(f)
    print("Schema:")
    print(pf.schema)
    df = pf.read_row_group(0).to_pandas()
    print("Columns:", list(df.columns))
    print(df.head(2))
