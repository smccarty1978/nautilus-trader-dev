import pandas as pd
import numpy as np

# Load study parquet
study_path = "studies/v_a_excursion_regime/results_v0/compression_vwap_study.parquet"
df_study = pd.read_parquet(study_path)
df_study_2024 = df_study[df_study["year"] == 2024].copy()

# Load backtest trades
backtest_path = "backtests/compression_vwap_launchpad/results/live_2024/trades.parquet"
df_backtest = pd.read_parquet(backtest_path)

print(f"Study 2024 total flips: {len(df_study_2024)}")
print(f"Backtest total trades: {len(df_backtest)}")

# For each backtest trade, let's find the corresponding flip in df_study_2024
# based on timestamp (entry_ts + 60s)
for idx, bt_row in df_backtest.iterrows():
    ts_flip = bt_row["entry_ts"] + 60_000_000_000
    flip = df_study_2024[df_study_2024["signal_time"] == ts_flip]
    if len(flip) == 0:
        print(f"BT Entry {ts_flip} (local ET) has NO corresponding flip in study parquet!")
    else:
        f = flip.iloc[0]
        # Check if it meets the criteria
        datetime_et = pd.to_datetime(f["signal_time"], utc=True).tz_convert("America/New_York")
        time_et = datetime_et.time()
        is_rth = (time_et >= pd.to_datetime("09:30:00").time()) & (time_et < pd.to_datetime("16:00:00").time())
        is_long = f["signal_direction"] == 1
        is_compressed = f["tot_slow"] < 22.0
        is_near_away = f["cell"] == "near-away"
        
        passed = is_rth and is_long and is_compressed and is_near_away
        if not passed:
            print(f"BT Entry {ts_flip} found in study, but failed criteria: "
                  f"rth={is_rth}, dir={f['signal_direction']}, tot_slow={f['tot_slow']:.2f}, cell={f['cell']}")

