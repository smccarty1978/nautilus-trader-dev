import pandas as pd
import numpy as np

# Load df_flips
df_flips = pd.read_parquet("studies/regime_classification/results/flips_excursion_paths.parquet")
df_bar1 = df_flips[df_flips["bar1_confirm"] == 1].copy()

# Deduplicate
df_dedup = df_bar1.groupby("entry_ts").agg({
    "entry_px_bar1": "first",
    "entry_px_flip": "first",
    "exit_ts": "first",
    "exit_px": "first",
    "signal_direction": "first",
    "entry_atr": "first",
    "year": "first",
    "regime_win_bar1": "first"
}).reset_index()

# Close Confirmed cohort
df_dedup["bar1_close_confirmed"] = ((df_dedup["entry_px_bar1"] - df_dedup["entry_px_flip"]) * df_dedup["signal_direction"] > 0).astype(int)
df_cohort = df_dedup[df_dedup["bar1_close_confirmed"] == 1].copy()

print(f"Total Close Confirmed: {len(df_cohort)}")
print(f"Win% in raw database: {df_cohort['regime_win_bar1'].mean():.2%}")

# Let's count how many have win == 1 in database vs PnL > 0
pnl_pts = (df_cohort["exit_px"] - df_cohort["entry_px_bar1"]) * df_cohort["signal_direction"]
win_pts_mask = pnl_pts > 0
print(f"Win% calculated as PnL > 0: {win_pts_mask.mean():.2%}")
print(f"Win% calculated as PnL >= 0: {(pnl_pts >= 0).mean():.2%}")

# Now let's see what happens to the subset of episodes that have a duration >= 3 minutes
# (i.e. exit_ts - entry_ts >= 180 seconds, meaning there is time for at least 1 control bar close)
df_cohort["duration_m"] = (df_cohort["exit_ts"] - df_cohort["entry_ts"]) / 60_000_000_000
df_long = df_cohort[df_cohort["duration_m"] >= 2.0]
print(f"\nSubset with duration >= 2 minutes: {len(df_long)}")
print(f"Win% in database for duration >= 2 min: {df_long['regime_win_bar1'].mean():.2%}")
print(f"Win% calculated as PnL > 0 for duration >= 2 min: {((df_long['exit_px'] - df_long['entry_px_bar1']) * df_long['signal_direction'] > 0).mean():.2%}")

df_long_3 = df_cohort[df_cohort["duration_m"] >= 3.0]
print(f"\nSubset with duration >= 3 minutes: {len(df_long_3)}")
print(f"Win% in database for duration >= 3 min: {df_long_3['regime_win_bar1'].mean():.2%}")
print(f"Win% calculated as PnL > 0 for duration >= 3 min: {((df_long_3['exit_px'] - df_long_3['entry_px_bar1']) * df_long_3['signal_direction'] > 0).mean():.2%}")
