import pandas as pd
import numpy as np
import struct

# Load 1m reference bar
f_1m = r"C:\Users\Scott McCarty\Projects\Nautilus Trader\data\catalog\NQ_v0_2020_2026\data\bar\NQ.XCME-1-MINUTE-LAST-EXTERNAL\2020-01-01T23-01-00-000000000Z_2026-04-30T00-00-00-000000000Z.parquet"
df_1m = pd.read_parquet(f_1m)

# Decode columns
for col in ['open', 'high', 'low', 'close', 'volume']:
    df_1m[col] = np.frombuffer(b''.join(df_1m[col].values), dtype=np.int64) / 10**9

df_1m.index = pd.to_datetime(df_1m['ts_event'], unit='ns', utc=True)
print("Decoded 1m df:")
print(df_1m.head(3))

# Load a few native 1s bars from 2020 to test aggregation
f_1s = r"C:\Users\Scott McCarty\Projects\Nautilus Trader\data\raw\NQ_v0_1s_2020.parquet"
df_1s = pd.read_parquet(f_1s, columns=['open', 'high', 'low', 'close', 'volume']).head(1000)
df_1s.index = pd.to_datetime(df_1s.index) # ts_event index

print("\nRaw 1s df:")
print(df_1s.head(3))

# Aggregate a minute
t_min = df_1s.index[0].floor('min')
rows_min = df_1s.loc[t_min : t_min + pd.Timedelta(seconds=59)]

print(f"\nAggregating for minute {t_min}:")
print(f"  Count: {len(rows_min)}")
if len(rows_min) > 0:
    agg_o = rows_min['open'].iloc[0]
    agg_h = rows_min['high'].max()
    agg_l = rows_min['low'].min()
    agg_c = rows_min['close'].iloc[-1]
    agg_v = rows_min['volume'].sum()
    print(f"  Aggregated: O={agg_o}, H={agg_h}, L={agg_l}, C={agg_c}, V={agg_v}")
    
    if t_min in df_1m.index:
        ref_row = df_1m.loc[t_min]
        if isinstance(ref_row, pd.DataFrame):
            ref_row = ref_row.iloc[0]
        print(f"  Reference:  O={ref_row['open']}, H={ref_row['high']}, L={ref_row['low']}, C={ref_row['close']}, V={ref_row['volume']}")
        print(f"  Match: O={np.isclose(agg_o, ref_row['open'])}, H={np.isclose(agg_h, ref_row['high'])}, L={np.isclose(agg_l, ref_row['low'])}, C={np.isclose(agg_c, ref_row['close'])}, V={np.isclose(agg_v, ref_row['volume'])}")
