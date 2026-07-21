import pandas as pd
import numpy as np

# Load study parquet
study_path = "studies/v_a_excursion_regime/results_v0/compression_vwap_study.parquet"
df_study = pd.read_parquet(study_path)
df_study_2024 = df_study[df_study["year"] == 2024].copy()

# Load backtest trades
backtest_path = "backtests/compression_vwap_launchpad/results/live_2024/trades.parquet"
df_backtest = pd.read_parquet(backtest_path)

# Let's inspect the 10 unmatched trades
for idx, bt_row in df_backtest.iterrows():
    ts_flip = bt_row["entry_ts"] + 60_000_000_000
    flip = df_study_2024[df_study_2024["signal_time"] == ts_flip]
    if len(flip) == 0:
        # Find the nearest flip in study
        diffs = df_study_2024["signal_time"] - ts_flip
        abs_diffs = np.abs(diffs)
        min_idx = abs_diffs.idxmin()
        min_diff_sec = diffs.loc[min_idx] / 1e9
        
        nearest_flip = df_study_2024.loc[min_idx]
        print(f"BT Entry ts_flip={ts_flip} has no exact match. Nearest study flip is at {nearest_flip['signal_time']} (Diff: {min_diff_sec:.1f}s), "
              f"dir={nearest_flip['signal_direction']}, cell={nearest_flip['cell']}")
