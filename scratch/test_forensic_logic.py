import pandas as pd
import numpy as np
import struct
import pytz

# Paths
rth_gaps_file = r"C:\Users\Scott McCarty\Projects\Nautilus Trader\unexplained_rth_gaps_over_30s.csv"
mcal_1m_file_early = r"C:\Users\Scott McCarty\Projects\Nautilus Trader\data\catalog\legacy\NQ_multi_year\data\bar\NQ.XCME-1-MINUTE-LAST-EXTERNAL\2016-01-03T23-01-00-000000000Z_2026-04-16T00-00-00-000000000Z.parquet"

df_gaps = pd.read_csv(rth_gaps_file)
print("Gaps loaded:", len(df_gaps))

# Read a few 1m reference bars to test decoding
df_1m = pd.read_parquet(mcal_1m_file_early).head(5)
print(df_1m)
