import pyarrow.parquet as pq
import glob
import os

raw_dir = r"C:\Users\Scott McCarty\Projects\Nautilus Trader\data\raw"
pattern = os.path.join(raw_dir, "NQ_v0_1s_*.parquet")
files = sorted(glob.glob(pattern))

if files:
    f = files[0]
    table = pq.read_table(f, columns=['ts_event'])
    print("Successfully read table with columns=['ts_event']")
    print(table.to_pandas().head(5))
