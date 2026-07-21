import pandas as pd
inspect_file = lambda p: print(f"Shape: {pd.read_parquet(p).shape}\nColumns: {list(pd.read_parquet(p).columns)}\nFirst 2:\n{pd.read_parquet(p).head(2)}")
inspect_file("studies/regime_classification/results/path_shape_nq.parquet")
