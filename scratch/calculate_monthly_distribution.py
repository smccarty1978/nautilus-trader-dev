import pandas as pd
import os

years = [2020, 2021, 2022, 2023, 2024, 2025, 2026]
all_dfs = []

for y in years:
    path = f"backtests/compression_vwap_launchpad/results/live_{y}/trades.parquet"
    if os.path.exists(path):
        df = pd.read_parquet(path)
        df["year"] = y
        all_dfs.append(df)

if not all_dfs:
    print("No trades found!")
    exit()

df_all = pd.concat(all_dfs, ignore_index=True)

# Convert entry_ts to datetime
df_all["dt"] = pd.to_datetime(df_all["entry_ts"], unit="ns", utc=True)
# Convert to America/New_York
df_all["dt_et"] = df_all["dt"].dt.tz_convert("America/New_York")
df_all["month"] = df_all["dt_et"].dt.month

print("Monthly Distribution of Trades (All Years Combined):")
monthly = df_all["month"].value_counts().sort_index()
months_names = {
    1: "January", 2: "February", 3: "March", 4: "April", 5: "May", 6: "June",
    7: "July", 8: "August", 9: "September", 10: "October", 11: "November", 12: "December"
}
for m, count in monthly.items():
    print(f"  {months_names[m]:<12}: {count} trades ({count / len(df_all):.1%})")
