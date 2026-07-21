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

print("First 15 Study Cohort signal timestamps:")
for t in study_cohort["signal_time"].tolist()[:15]:
    print(t, pd.to_datetime(t, utc=True).tz_convert("America/New_York"))

print("\nFirst 15 Backtest entry timestamps:")
for t in df_backtest["entry_ts"].tolist()[:15]:
    print(t, pd.to_datetime(t, utc=True).tz_convert("America/New_York"))
