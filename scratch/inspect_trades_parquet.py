import pandas as pd
from pathlib import Path

p = Path("backtests/baseline_flip_parity/results/nq_live_2020_stall_sma13_s3_g0_long/trades.parquet")
if p.exists():
    df = pd.read_parquet(p)
    print("Columns:", df.columns.tolist())
    print("Shape:", df.shape)
    print("Head:\n", df.head())
else:
    print("Trades parquet not found.")
