import pandas as pd

f_gaps = r"C:\Users\Scott McCarty\Projects\Nautilus Trader\long_gap_classification.csv"
df = pd.read_csv(f_gaps)
df_eth = df[df['RTH_or_ETH'] == 'ETH']

# Longest gaps first
long_gaps = df_eth[df_eth['missing_seconds'] > 1800].sort_values(by='missing_seconds', ascending=False)
print("Longest ETH gaps (>30 minutes):")
print(long_gaps.to_dict('records'))
