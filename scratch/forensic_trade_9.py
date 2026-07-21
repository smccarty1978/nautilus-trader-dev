import pandas as pd
import numpy as np

# Load bars for 2026
bars = pd.read_parquet("data/raw/NQ_v0_1s_2026_ytd.parquet")
if bars.index.tz is None:
    bars.index = bars.index.tz_localize("UTC")
    
# Convert index to ns
ts_ns = bars.index.astype("int64").to_numpy()
highs = bars["high"].to_numpy()
lows = bars["low"].to_numpy()
closes = bars["close"].to_numpy()

# Trade 9 details
# entry_ts = 1769783460000000000
entry_ts = 1769783460000000000
entry_px = 25896.50
atr = 19.907466
direction = 1 # Long

pt1 = entry_px + 0.50 * atr # 25906.45 -> rounded 25906.50
pt2 = entry_px + 2.00 * atr # 25936.31 -> rounded 25936.25
sl = entry_px - 1.50 * atr # 25866.64 -> rounded 25866.75 or 25866.50? In backtest it exited at 25866.25

print(f"Long entry at {entry_px} at {pd.to_datetime(entry_ts, unit='ns', utc=True)}")
print(f"PT1: {pt1:.2f}, PT2: {pt2:.2f}, SL: {sl:.2f}")

idx_start = np.searchsorted(ts_ns, entry_ts, side="left")
print(f"Start index in bars: {idx_start}")

# Print first 20 bars
print("\nFirst 20 bars after entry:")
for i in range(idx_start, idx_start + 20):
    t_dt = pd.to_datetime(ts_ns[i], unit='ns', utc=True)
    print(f"Bar {t_dt}: H={highs[i]:.2f}, L={lows[i]:.2f}, C={closes[i]:.2f}")
