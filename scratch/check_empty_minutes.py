import pandas as pd

impact_csv = r"C:\Users\Scott McCarty\Projects\Nautilus Trader\eth_gap_1m_impact.csv"
df = pd.read_csv(impact_csv)
print(df['reconciliation_status'].value_counts())
print(f"Total rows: {len(df):,}")
