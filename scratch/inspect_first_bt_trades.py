import pandas as pd

df_bt = pd.read_parquet("backtests/baseline_flip_parity/results/nq_live_2025/trades.parquet")
df_bt["dt_entry"] = pd.to_datetime(df_bt["entry_ts"], unit="ns", utc=True)
print("First 15 backtest trades:")
print(df_bt.head(15)[["dt_entry", "entry_px", "entry_atr", "signal_direction", "exit_reason"]])
