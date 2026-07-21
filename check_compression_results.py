import os
import pandas as pd

years = [2020, 2021, 2022, 2023, 2024, 2025, 2026]
for y in years:
    path = f"backtests/compression_vwap_launchpad/results/live_{y}/trades.parquet"
    if os.path.exists(path):
        try:
            df = pd.read_parquet(path)
            print(f"Year {y}: {len(df)} trades in parquet")
        except Exception as e:
            print(f"Year {y}: Error reading parquet: {e}")
    else:
        print(f"Year {y}: Parquet does not exist at {path}")
