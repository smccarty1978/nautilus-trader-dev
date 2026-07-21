import pandas as pd
from pathlib import Path

root = Path("c:/Users/Scott McCarty/Projects/Nautilus Trader")
years = [2020, 2021, 2022, 2023, 2024, 2025, 2026]

for y in years:
    p = root / f"backtests/baseline_flip_parity/results/nq_live_{y}_stall_sma13_s3_g0_long/trades.parquet"
    if p.exists():
        df = pd.read_parquet(p)
        print(f"Year {y}: {len(df)} trades")
    else:
        print(f"Year {y}: Not Found")
