import os, sys
from pathlib import Path
import pandas as pd
import numpy as np

PROJECT_ROOT = Path("c:/Users/Scott McCarty/Projects/Nautilus Trader")
sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)

from backtests.baseline_flip_parity.strategy import RegimeState

def main():
    print("Loading 1s NQ bars for 2025...")
    df = pd.read_parquet("data/raw/NQ_v0_1s_2025.parquet")
    
    print("Resampling to 1m bars...")
    df_1m = pd.DataFrame()
    df_1m["open"] = df["open"].resample("1Min").first()
    df_1m["high"] = df["high"].resample("1Min").max()
    df_1m["low"] = df["low"].resample("1Min").min()
    df_1m["close"] = df["close"].resample("1Min").last()
    df_1m = df_1m.dropna()
    
    print("Simulating RegimeState...")
    rs = RegimeState()
    regimes = []
    for idx, r in df_1m.iterrows():
        rg = rs.update(r["high"], r["low"], r["close"])
        regimes.append(rg)
        
    df_1m["regime"] = regimes
    df_1m["prev_regime"] = df_1m["regime"].shift(1)
    df_1m["flip"] = (df_1m["prev_regime"] != 0) & (df_1m["regime"] != 0) & (df_1m["prev_regime"] != df_1m["regime"])
    
    flips_sim = df_1m[df_1m["flip"]].copy()
    flips_sim["ts"] = flips_sim.index.values.astype("int64")
    
    print("Loading offline flips...")
    df_flips = pd.read_parquet("studies/regime_classification/results/flips_excursion_paths.parquet")
    df_flips_2025 = df_flips[df_flips["year"] == 2025].copy()
    
    print(f"Simulated flips count: {len(flips_sim):,}")
    print(f"Offline flips count:  {len(df_flips_2025):,}")
    
    sim_ts = set(flips_sim["ts"].tolist())
    off_ts = set(df_flips_2025["entry_ts"].values.astype("int64").tolist())
    
    common = sim_ts.intersection(off_ts)
    print(f"Common flips:         {len(common):,}")
    print(f"Simulated only:       {len(sim_ts - off_ts):,}")
    print(f"Offline only:         {len(off_ts - sim_ts):,}")
    
    # Print first 5 simulated only
    print("\nFirst 5 simulated only:")
    for ts in sorted(list(sim_ts - off_ts))[:5]:
        print(pd.Timestamp(ts, unit="ns", tz="UTC"))
        
    # Print first 5 offline only
    print("\nFirst 5 offline only:")
    for ts in sorted(list(off_ts - sim_ts))[:5]:
        print(pd.Timestamp(ts, unit="ns", tz="UTC"))

if __name__ == "__main__":
    main()
