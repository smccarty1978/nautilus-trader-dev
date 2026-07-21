import pandas as pd

def main():
    ex_p = "studies/regime_classification/results/flips_excursion_paths.parquet"
    df = pd.read_parquet(ex_p)
    print(f"Total rows in flips_excursion_paths: {len(df):,}")
    print("\nBy year:")
    print(df["year"].value_counts().sort_index())
    
    print("\nbar1_confirm True counts by year:")
    print(df[df["bar1_confirm"]]["year"].value_counts().sort_index())
    
    print("\nbar1_confirm False counts by year:")
    print(df[~df["bar1_confirm"]]["year"].value_counts().sort_index())

if __name__ == "__main__":
    main()
