import pandas as pd
import numpy as np

def main():
    ds_path = "scratch/bar1_conditioning_dataset.parquet"
    live_path = "backtests/baseline_flip_parity/results/nq_live_2025_base/trades.parquet"
    
    df_ds = pd.read_parquet(ds_path)
    df_ds = df_ds[df_ds["year"] == 2025]
    
    df_live = pd.read_parquet(live_path)
    
    print(f"Conditioning Dataset (DS) 2025 count: {len(df_ds):,}")
    print(f"Live Backtest 2025 count:             {len(df_live):,}")
    
    # Check if there is an RTH or hours filter in DS
    # DS entry_ts_bar1 is nanoseconds
    df_ds["dt"] = pd.to_datetime(df_ds["entry_ts_bar1"], unit="ns", utc=True)
    df_ds["ct"] = df_ds["dt"].dt.tz_convert("America/Chicago")
    df_ds["hour"] = df_ds["ct"].dt.hour
    df_ds["minute"] = df_ds["ct"].dt.minute
    df_ds["time_min"] = df_ds["hour"] * 60 + df_ds["minute"]
    
    df_live["dt"] = pd.to_datetime(df_live["entry_ts"], unit="ns", utc=True)
    df_live["ct"] = df_live["dt"].dt.tz_convert("America/Chicago")
    df_live["hour"] = df_live["ct"].dt.hour
    df_live["minute"] = df_live["ct"].dt.minute
    df_live["time_min"] = df_live["hour"] * 60 + df_live["minute"]
    
    print("\nDS Hours distribution (top 10):")
    print(df_ds["hour"].value_counts().head(10).to_string())
    
    print("\nLive Hours distribution (top 10):")
    print(df_live["hour"].value_counts().head(10).to_string())
    
    # Check if RTH-only
    ds_rth = df_ds[(df_ds["time_min"] >= 510) & (df_ds["time_min"] < 900)]
    live_rth = df_live[(df_live["time_min"] >= 510) & (df_live["time_min"] < 900)]
    print(f"\nDS RTH trades (8:30 - 15:00 CT): {len(ds_rth):,} ({len(ds_rth)/len(df_ds):.1%})")
    print(f"Live RTH trades (8:30 - 15:00 CT): {len(live_rth):,} ({len(live_rth)/len(df_live):.1%})")
    
    # Check if there is an HMM state or other feature filter in DS
    # Let's check columns in DS
    print("\nDS Columns:")
    print(list(df_ds.columns))
    
    # Are there any NaN values in key lookup columns in DS?
    # Or is it possible that snaps database only had RTH snapshots, or had a filter?
    # Let's look at snap file for 2025:
    snap_p = "studies/1m_regime_collector_v2/results/v2_feature_snapshots_2025.parquet"
    df_snap = pd.read_parquet(snap_p)
    print(f"\nSnapshots database count: {len(df_snap):,}")
    df_snap_zero = df_snap[df_snap["checkpoint_s"] == 0]
    print(f"Snapshots database checkpoint_s==0 count: {len(df_snap_zero):,}")
    
    # Let's look at flips_excursion_paths.parquet
    ex_p = "studies/regime_classification/results/flips_excursion_paths.parquet"
    df_ex = pd.read_parquet(ex_p)
    df_ex_2025 = df_ex[(df_ex["year"] == 2025) & df_ex["bar1_confirm"]]
    print(f"\nflips_excursion_paths.parquet 2025 confirmed trades count: {len(df_ex_2025):,}")

if __name__ == "__main__":
    main()
