import os, sys
import pandas as pd
import numpy as np
from pathlib import Path

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
    
    target_start = 1735790520000000000 - 25 * 60 * 1_000_000_000
    target_end = 1735790520000000000 + 10 * 60 * 1_000_000_000
    
    full_1m = one_m[one_m.index <= target_end].copy()
    
    e3h = e9h = e3l = e9l = 0.0
    reg = np.zeros(len(full_1m), dtype=int)
    
    cur = 0
    m_h, m_l, m_c = full_1m["h"].values, full_1m["l"].values, full_1m["c"].values
    for i in range(len(full_1m)):
        if i == 0:
            e3h = m_h[i]; e9h = m_h[i]; e3l = m_l[i]; e9l = m_l[i]
        else:
            e3h = ALPHA_EMA3 * m_h[i] + (1.0 - ALPHA_EMA3) * e3h
            e9h = ALPHA_EMA9 * m_h[i] + (1.0 - ALPHA_EMA9) * e9h
            e3l = ALPHA_EMA3 * m_l[i] + (1.0 - ALPHA_EMA3) * e3l
            e9l = ALPHA_EMA9 * m_l[i] + (1.0 - ALPHA_EMA9) * e9l
        
        new_reg = cur
        if m_c[i] > e3h and m_c[i] > e9h:
            new_reg = 1
        elif m_c[i] < e3l and m_c[i] < e9l:
            new_reg = -1
            
        reg[i] = new_reg
        cur = new_reg
        
    full_1m["regime"] = reg
    
    sub_full = full_1m[(full_1m.index >= target_start) & (full_1m.index <= target_end)].copy()
    sub_full.index = pd.to_datetime(sub_full.index, unit="ns", utc=True)
    
    pd.set_option('display.max_columns', None)
    pd.set_option('display.width', 1000)
    print("=== nt_regime_exit_cohort calculation ===")
    print(sub_full[["o", "h", "l", "c", "regime"]])

if __name__ == "__main__":
    run()
