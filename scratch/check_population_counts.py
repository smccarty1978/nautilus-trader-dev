import pandas as pd
from pathlib import Path

RES = Path("studies/regime_flip_truth/results")
YEARS = [2021, 2022, 2023, 2024]

for y in YEARS:
    ep = RES / f"flip_truth_dataset_{y}.parquet"
    if ep.exists():
        df = pd.read_parquet(ep)
        print(f"Year {y}:")
        print(f"  Total rows: {len(df):,}")
        print(f"  Population A (raw flips): {len(df[df.population == 'A']):,}")
        print(f"  Population B (confirmed flips): {len(df[df.population == 'B']):,}")
        # Warmed up counts
        print(f"  Warmed up A: {len(df[(df.population == 'A') & df.warmed_up]):,}")
        print(f"  Warmed up B: {len(df[(df.population == 'B') & df.warmed_up]):,}")
