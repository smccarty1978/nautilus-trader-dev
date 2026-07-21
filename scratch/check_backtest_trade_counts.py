import pandas as pd
from pathlib import Path

PROJECT_ROOT = Path("c:/Users/Scott McCarty/Projects/Nautilus Trader")

YEARS = [2021, 2022, 2023, 2024]

print("BASELINE PARITY:")
for y in YEARS:
    p = PROJECT_ROOT / f"backtests/baseline_flip_parity/results/nq_live_{y}_base/trades.parquet"
    if p.exists():
        df = pd.read_parquet(p)
        print(f"  Year {y}: {len(df):,} trades")
    else:
        print(f"  Year {y}: not found")

print("\nTRAILING STOP:")
for y in YEARS:
    p = PROJECT_ROOT / f"backtests/baseline_flip_parity/results/nq_live_{y}_trail_tp1.5_sl1.0/trades.parquet"
    if p.exists():
        df = pd.read_parquet(p)
        print(f"  Year {y}: {len(df):,} trades")
    else:
        print(f"  Year {y}: not found")
