import pandas as pd
import numpy as np

f_gaps = r"C:\Users\Scott McCarty\Projects\Nautilus Trader\long_gap_classification.csv"
df = pd.read_csv(f_gaps)

# Filter for ETH
df_eth = df[df['RTH_or_ETH'] == 'ETH'].copy()
print(f"Total ETH gaps: {len(df_eth):,}")

# Let's count classifications in the raw df first
print("\nRaw classifications in ETH:")
print(df_eth['classification'].value_counts())

# Let's see the distribution of duration for raw 'OPEN_SESSION_UNEXPLAINED' in ETH
df_unexp = df_eth[df_eth['classification'] == 'OPEN_SESSION_UNEXPLAINED']
print(f"\nRaw unexplained ETH gaps: {len(df_unexp):,}")
print(f"  <= 300s: {np.sum(df_unexp['missing_seconds'] <= 300):,}")
print(f"  > 300s:  {np.sum(df_unexp['missing_seconds'] > 300):,}")
print(f"  > 1800s: {np.sum(df_unexp['missing_seconds'] > 1800):,}")
