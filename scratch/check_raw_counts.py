import pandas as pd
from pathlib import Path

def main():
    p1 = Path("studies/regime_classification/results/flips_excursion_paths.parquet")
    p2 = Path("studies/v_a_excursion_regime/results_v0/flips_excursion_7yr.parquet")
    
    if p1.exists():
        df1 = pd.read_parquet(p1)
        print(f"p1: flips_excursion_paths.parquet count: {len(df1):,}")
        if "year" in df1.columns:
            print(df1["year"].value_counts().sort_index())
    else:
        print("p1 not found")
        
    if p2.exists():
        df2 = pd.read_parquet(p2)
        print(f"p2: flips_excursion_7yr.parquet count: {len(df2):,}")
        if "year" in df2.columns:
            print(df2["year"].value_counts().sort_index())
    else:
        print("p2 not found")

if __name__ == "__main__":
    main()
