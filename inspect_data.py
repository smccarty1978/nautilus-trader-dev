import pandas as pd
from pathlib import Path

fp = Path("studies/1m_regime_collector_v2/results/v2_feature_snapshots_2024.parquet")
if fp.exists():
    df = pd.read_parquet(fp)
    print(f"Loaded snapshots: {len(df):,}")
    print("Columns:", df.columns.tolist())
    # unique flips
    flips = df.drop_duplicates(subset=["signal_time", "signal_direction"])
    print(f"Unique flips: {len(flips):,}")
    longs = flips[flips["signal_direction"] == 1]
    print(f"Unique long flips: {len(longs):,}")
    # print head
    print(longs.head(5))
else:
    print(f"{fp} does not exist")
