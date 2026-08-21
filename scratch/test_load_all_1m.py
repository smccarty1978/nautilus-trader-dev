import pandas as pd
import numpy as np
import time

t0 = time.time()
f_early = r"C:\Users\Scott McCarty\Projects\Nautilus Trader\data\catalog\legacy\NQ_multi_year\data\bar\NQ.XCME-1-MINUTE-LAST-EXTERNAL\2016-01-03T23-01-00-000000000Z_2026-04-16T00-00-00-000000000Z.parquet"
f_recent = r"C:\Users\Scott McCarty\Projects\Nautilus Trader\data\catalog\NQ_v0_2020_2026\data\bar\NQ.XCME-1-MINUTE-LAST-EXTERNAL\2020-01-01T23-01-00-000000000Z_2026-04-30T00-00-00-000000000Z.parquet"

df_early = pd.read_parquet(f_early)
df_recent = pd.read_parquet(f_recent)

print(f"Loaded early ({len(df_early):,}) and recent ({len(df_recent):,}) in {time.time() - t0:.2f}s")

# Let's decode both and merge
t0 = time.time()
for col in ['open', 'high', 'low', 'close', 'volume']:
    df_early[col] = np.frombuffer(b''.join(df_early[col].values), dtype=np.int64) / 10**9
    df_recent[col] = np.frombuffer(b''.join(df_recent[col].values), dtype=np.int64) / 10**9

df_early.index = pd.to_datetime(df_early['ts_event'], unit='ns', utc=True)
df_recent.index = pd.to_datetime(df_recent['ts_event'], unit='ns', utc=True)

df_1m = pd.concat([df_early, df_recent])
df_1m = df_1m[~df_1m.index.duplicated(keep='first')]

print(f"Merged and de-duplicated: {len(df_1m):,} rows in {time.time() - t0:.2f}s")
