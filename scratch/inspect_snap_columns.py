import pandas as pd
from pathlib import Path

p = Path("studies/1m_regime_collector_v2/results/v2_feature_snapshots_2025.parquet")
if p.exists():
    df = pd.read_parquet(p)
    print(f"Shape: {df.shape}")
    cols = list(df.columns)
    matching = [c for c in cols if "bar1" in c or "close" in c]
    print(f"Columns matching 'bar1' or 'close': {matching}")
else:
    print(f"File {p} does not exist")
