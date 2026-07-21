import pandas as pd

def inspect_file(path):
    print(f"\n==========================================")
    print(f"File: {path}")
    df = pd.read_parquet(path)
    print(f"Shape: {df.shape}")
    print(f"Columns: {list(df.columns)}")
    print(f"First 3 rows:\n{df.head(3)}")
    if "year" in df.columns:
        print(f"Year counts:\n{df['year'].value_counts().sort_index()}")

inspect_file("studies/regime_classification/results/states_nq_1m.parquet")
inspect_file("studies/regime_classification/results/states_nq_5m.parquet")
