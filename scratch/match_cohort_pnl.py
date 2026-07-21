import pandas as pd
import numpy as np

# Load study parquet
study_path = "studies/v_a_excursion_regime/results_v0/compression_vwap_study.parquet"
df_study = pd.read_parquet(study_path)
df_study_2024 = df_study[df_study["year"] == 2024].copy()

# Filter study to RTH long-only compressed near-away
df_study_2024["datetime_et"] = pd.to_datetime(df_study_2024["signal_time"], utc=True).dt.tz_convert("America/New_York")
df_study_2024["time_et"] = df_study_2024["datetime_et"].dt.time
is_rth = (df_study_2024["time_et"] >= pd.to_datetime("09:30:00").time()) & (df_study_2024["time_et"] < pd.to_datetime("16:00:00").time())
is_long = df_study_2024["signal_direction"] == 1
is_compressed = df_study_2024["tot_slow"] < 22.0
is_near_away = df_study_2024["cell"] == "near-away"

study_cohort = df_study_2024[is_rth & is_long & is_compressed & is_near_away].copy()
study_cohort = study_cohort.sort_values("signal_time")

# Load backtest trades
backtest_path = "backtests/compression_vwap_launchpad/results/live_2024/trades.parquet"
df_backtest = pd.read_parquet(backtest_path)
df_backtest = df_backtest.sort_values("entry_ts")

print(f"Study Cohort trades: {len(study_cohort)}")
print(f"Backtest trades: {len(df_backtest)}")

print("\nFirst 5 trades in Study Cohort:")
print(study_cohort[["signal_time", "close_at_T", "atr_at_signal", "hit"]].head())

print("\nFirst 5 trades in Backtest:")
# Let's inspect the columns of df_backtest first
print(df_backtest.columns)
print(df_backtest[["entry_ts", "entry_px", "entry_atr", "exit_reason", "t1_filled"]].head())

# Let's calculate the exact matches
# We will match based on timestamp: entry_ts in backtest represents the signal timestamp or decision time.
# Let's see if the difference between signal_time and entry_ts is small or 0.
matches = 0
for idx, bt_row in df_backtest.iterrows():
    # Find matching study flip: study signal_time should match bt_row['entry_ts'] closely
    # Wait, in strategy.py, entry_ts = ts, which is the ts_event of the 1s bar that triggers check_entry.
    # In NT, check_entry is called when the 1m bar closes. The 1m bar closes on the 1s boundary.
    # So entry_ts is the nanosecond timestamp of the 1m close.
    # In study, signal_time is also the nanosecond timestamp of the 1m flip.
    # Let's find exact matches or within 1s.
    diffs = study_cohort["signal_time"] - bt_row["entry_ts"]
    abs_diffs = np.abs(diffs)
    min_idx = abs_diffs.idxmin()
    min_diff_sec = diffs.loc[min_idx] / 1e9
    
    if np.abs(min_diff_sec - 60.0) < 5.0:
        matches += 1
    else:
        print(f"BT Entry {bt_row['entry_ts']} nearest is signal {study_cohort.loc[min_idx, 'signal_time']} (Diff: {min_diff_sec}s)")

print(f"\nMatching trades count (within 5s of 60s offset): {matches} / {len(df_backtest)}")


