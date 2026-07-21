import pandas as pd
import numpy as np
from pathlib import Path

def print_audit_for_run(run_name, trades_path, events_path, dataset_path):
    if not trades_path.exists():
        print(f"Error: {trades_path} not found. Run the backtest first.")
        return
        
    df_bt = pd.read_parquet(trades_path)
    df_ev = pd.read_parquet(events_path)
    df_ds = pd.read_parquet(dataset_path)
    df_ds = df_ds[df_ds["year"] == 2025]

    df_bt["minute_ts"] = (df_bt["entry_ts"] // 60_000_000_000) * 60_000_000_000
    df_ev["minute_ts"] = (df_ev["signal_time"] // 60_000_000_000) * 60_000_000_000
    df_ds["minute_ts"] = (df_ds["entry_ts_bar1"] // 60_000_000_000) * 60_000_000_000

    bt_times = set(df_bt["minute_ts"].astype("int64"))
    ev_times = set(df_ev["minute_ts"].astype("int64"))
    ds_times = set(df_ds["minute_ts"].astype("int64"))

    print("================================================================================")
    print(f"                      TRADE PARITY AUDIT SUMMARY: {run_name}")
    print("================================================================================")
    print(f"Total live backtest trades:               {len(df_bt):,}")
    print(f"Total collector events (offline raw):     {len(df_ev):,}")
    print(f"Total conditioning dataset trades (DS):   {len(df_ds):,}")
    print(f"--------------------------------------------------------------------------------")

    matched_bt_ev = bt_times.intersection(ev_times)
    matched_bt_ds = bt_times.intersection(ds_times)
    matched_ds_ev = ds_times.intersection(ev_times)

    print(f"Live trades matched with Collector Events: {len(matched_bt_ev):,} ({len(matched_bt_ev)/len(df_bt):.1%})")
    print(f"Live trades matched with DS trades:        {len(matched_bt_ds):,} ({len(matched_bt_ds)/len(df_bt):.1%})")
    print(f"DS trades matched with Collector Events:   {len(matched_ds_ev):,} ({len(matched_ds_ev)/len(df_ds):.1%})")
    print(f"--------------------------------------------------------------------------------")
    print(f"Dataset trades NOT in live backtest:       {len(ds_times - bt_times):,}")
    print(f"Live trades NOT in dataset (DS):           {len(bt_times - ds_times):,}")
    extra_in_ev = (bt_times - ds_times).intersection(ev_times)
    print(f"  -> Of these, how many exist in Collector Events? {len(extra_in_ev):,} ({len(extra_in_ev)/len(bt_times - ds_times):.1%})")
    print(f"--------------------------------------------------------------------------------")
    
    # Calculate performance metrics if we can estimate PnL from raw trades
    # PnL in USD = (exit_px - entry_px) * direction * 20.0
    # PnL in ATR = PnL in USD / (entry_atr * 20.0)
    # Wait, do we have exit price or exit reason?
    # In trades.parquet: entry_px, entry_atr, signal_direction, exit_reason
    # Wait, we don't have exit price recorded in trades.parquet!
    # But wait, did we write exit price?
    # Let's check: in strategy.py:
    # "entry_px": self._entry_px, "entry_atr": self._entry_atr, "signal_direction": self._entry_dir
    # So we don't have exit price in trades.parquet.
    # But wait, we can compute PnL by matching trades with 1s bars and replicating the exit price!
    # Or we can check if strategy.py has exit_px or exit_ts we can add to trades.parquet!
    # Wait, we can easily add exit_px and exit_ts to trades.parquet by modifying strategy.py.
    # But since the runs are already finished, let's write a quick simulation parser or update strategy.py to include exit_px and exit_ts, and run them again!
    # Wait, since running them takes 200 seconds, let's update strategy.py to record exit_px and exit_ts, and run them again so we have exact PnL and Profit Factors!
    # That is extremely clean and professional.
    print("================================================================================")

def main():
    events_path = Path("studies/1m_regime_collector_v2/results/v2_event_summary_2025.parquet")
    dataset_path = Path("scratch/bar1_conditioning_dataset.parquet")

    # Let's check if the directory has trades.parquet:
    base_trades = Path("backtests/baseline_flip_parity/results/nq_live_2025_base/trades.parquet")
    stall_trades = Path("backtests/baseline_flip_parity/results/nq_live_2025_stall/trades.parquet")

    if base_trades.exists():
        print_audit_for_run("2025 BASELINE", base_trades, events_path, dataset_path)
    if stall_trades.exists():
        print_audit_for_run("2025 STALL PROTECTION", stall_trades, events_path, dataset_path)

if __name__ == "__main__":
    main()
