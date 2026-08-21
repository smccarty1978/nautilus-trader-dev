import pandas as pd
import numpy as np
import time

f = r"C:\Users\Scott McCarty\Projects\Nautilus Trader\data\catalog\legacy\NQ_multi_year\data\bar\NQ.XCME-1-MINUTE-LAST-EXTERNAL\2016-01-03T23-01-00-000000000Z_2026-04-16T00-00-00-000000000Z.parquet"
t0 = time.time()
df = pd.read_parquet(f)
print(f"Loaded parquet in {time.time() - t0:.2f}s")

t0 = time.time()
# Join and frombuffer
open_bytes = df['open'].values
combined = b''.join(open_bytes)
open_ints = np.frombuffer(combined, dtype=np.int64)
print(f"Decoded {len(open_ints):,} values in {time.time() - t0:.2f}s")
print("First 5 values:", open_ints[:5] / 10**9)
