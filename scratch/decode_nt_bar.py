import pandas as pd
import struct

f = r"C:\Users\Scott McCarty\Projects\Nautilus Trader\data\catalog\legacy\NQ_multi_year\data\bar\NQ.XCME-1-MINUTE-LAST-EXTERNAL\2016-01-03T23-01-00-000000000Z_2026-04-16T00-00-00-000000000Z.parquet"
df = pd.read_parquet(f).head(5)

for idx, row in df.iterrows():
    # Let's decode the bytes
    open_bytes = row['open']
    high_bytes = row['high']
    low_bytes = row['low']
    close_bytes = row['close']
    volume_bytes = row['volume']
    
    # Unpack as uint64 or int64
    o_val = struct.unpack('<Q', open_bytes)[0]
    h_val = struct.unpack('<Q', high_bytes)[0]
    l_val = struct.unpack('<Q', low_bytes)[0]
    c_val = struct.unpack('<Q', close_bytes)[0]
    v_val = struct.unpack('<Q', volume_bytes)[0]
    
    print(f"Index: {idx}")
    print(f"  open:   {o_val}")
    print(f"  high:   {h_val}")
    print(f"  low:    {l_val}")
    print(f"  close:  {c_val}")
    print(f"  volume: {v_val}")
    print(f"  ts_event: {row['ts_event']}")
    print(f"  ts_init:  {row['ts_init']}")
