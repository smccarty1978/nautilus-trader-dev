import pandas as pd
import os

p = "backtests/hmm_state_filtered/results/nq_hmm_4_s3_2024/trades.parquet"
if os.path.exists(p):
    df = pd.read_parquet(p)
    print(f"Loaded {len(df)} trades from {p}")
    print(f"Columns: {list(df.columns)}")
    print("\nFirst 5 trades:")
    print(df.head())
    print("\nValue counts for exit reasons:")
    if "exit_reason" in df.columns:
        print(df["exit_reason"].value_counts())
    else:
        print("No exit_reason column present!")
else:
    print(f"File {p} does not exist!")
