import os, sys
import pandas as pd
import numpy as np
from pathlib import Path

# Local EMA/Regime calculation logic
ALPHA_EMA3 = 0.5
ALPHA_EMA9 = 0.2

def run():
    p = "data/raw/NQ_v0_1s_2025.parquet"
    if not os.path.exists(p):
        print("Error: 1s data not found")
        return
    bars_1s = pd.read_parquet(p, columns=["open", "high", "low", "close"])
    if bars_1s.index.tz is None:
        bars_1s.index = bars_1s.index.tz_localize("UTC")
        
    ts = bars_1s.index.values.astype(np.int64)
    bucket = (ts // 60_000_000_000) * 60_000_000_000
    g = pd.DataFrame({
        "b": bucket,
        "o": bars_1s["open"].values,
        "h": bars_1s["high"].values,
        "l": bars_1s["low"].values,
        "c": bars_1s["close"].values
    })
    one_m = g.groupby("b").agg(o=("o", "first"), h=("h", "max"), l=("l", "min"), c=("c", "last"))
    
    target_start = 1735790100000000000 - 15 * 60 * 1_000_000_000
    target_end = 1735790100000000000 + 20 * 60 * 1_000_000_000
    
    full_1m = one_m[one_m.index <= target_end].copy()
    
    e3h = e9h = e3l = e9l = None
    reg = np.zeros(len(full_1m), dtype=int)
    ema3h_arr = np.zeros(len(full_1m))
    ema9h_arr = np.zeros(len(full_1m))
    ema3l_arr = np.zeros(len(full_1m))
    ema9l_arr = np.zeros(len(full_1m))
    
    m_h, m_l, m_c = full_1m["h"].values, full_1m["l"].values, full_1m["c"].values
    for i in range(len(full_1m)):
        h, l, c = m_h[i], m_l[i], m_c[i]
        if i == 0:
            e3h = h; e9h = h; e3l = l; e9l = l
        else:
            e3h = ALPHA_EMA3 * h + (1.0 - ALPHA_EMA3) * e3h
            e9h = ALPHA_EMA9 * h + (1.0 - ALPHA_EMA9) * e9h
            e3l = ALPHA_EMA3 * l + (1.0 - ALPHA_EMA3) * e3l
            e9l = ALPHA_EMA9 * l + (1.0 - ALPHA_EMA9) * e9l
        
        # In strategy.py:
        # prev = self.regime
        # if c > self.ema3_h and c > self.ema9_h: self.regime = 1
        # elif c < self.ema3_l and c < self.ema9_l: self.regime = -1
        # self.regime_flipped = (self.regime != prev and self.regime != 0)
        # Note: self.regime starts at 0.
        if i == 0:
            cur_reg = 0
        else:
            cur_reg = reg[i-1]
            
        if c > e3h and c > e9h:
            new_reg = 1
        elif c < e3l and c < e9l:
            new_reg = -1
        else:
            new_reg = cur_reg
            
        reg[i] = new_reg
        ema3h_arr[i] = e3h
        ema9h_arr[i] = e9h
        ema3l_arr[i] = e3l
        ema9l_arr[i] = e9l
        
    full_1m["regime"] = reg
    full_1m["ema3h"] = ema3h_arr
    full_1m["ema9h"] = ema9h_arr
    full_1m["ema3l"] = ema3l_arr
    full_1m["ema9l"] = ema9l_arr
    
    sub = full_1m[(full_1m.index >= target_start) & (full_1m.index <= target_end)].copy()
    sub.index = pd.to_datetime(sub.index, unit="ns", utc=True)
    pd.set_option('display.max_columns', None)
    pd.set_option('display.width', 1000)
    print(sub[["o", "h", "l", "c", "ema3h", "ema9h", "ema3l", "ema9l", "regime"]])

if __name__ == "__main__":
    run()
