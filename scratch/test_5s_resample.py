import pandas as pd
import numpy as np

p_1s = 'data/raw/NQ_v0_1s_2023.parquet'
df_1s = pd.read_parquet(p_1s, columns=['open', 'high', 'low', 'close']).iloc[:60]
df_5s = df_1s.resample('5s').agg({'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last'}).dropna()
print("1s index head:")
print(df_1s.index[:10])
print("5s resampled head:")
print(df_5s.head())
