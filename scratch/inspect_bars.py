import pandas as pd
from pathlib import Path
from nautilus_trader.persistence.catalog import ParquetDataCatalog

catalog_path = "data/catalog/NQ_v0_2020_2026"
catalog = ParquetDataCatalog(catalog_path)

print("Loading 1s bars for 2022...")
load_start = pd.Timestamp("2022-01-01", tz="UTC")
load_end = pd.Timestamp("2022-12-31 23:59:59", tz="UTC")
bars_1s = catalog.bars(
    bar_types=["NQ.XCME-1-SECOND-LAST-EXTERNAL"],
    start=load_start, end=load_end
)
print(f"Loaded {len(bars_1s):,} 1s bars")

if len(bars_1s) > 0:
    ts_list = [b.ts_event for b in bars_1s]
    df = pd.DataFrame({"ts": ts_list})
    df["dt"] = pd.to_datetime(df["ts"], unit="ns", utc=True)
    df["minute"] = df["dt"].dt.floor("min")
    total_unique_minutes = df["minute"].nunique()
    print(f"Total unique minutes in all loaded bars for 2022: {total_unique_minutes:,}")

    # Let's count how many are RTH (9:30-16:00 ET)
    # Convert dt to America/New_York
    df["dt_et"] = df["dt"].dt.tz_convert("America/New_York")
    rth_mask = (df["dt_et"].dt.time >= pd.Timestamp("09:30").time()) & (df["dt_et"].dt.time < pd.Timestamp("16:00").time())
    df_rth = df[rth_mask]
    total_rth_unique_minutes = df_rth["minute"].nunique()
    print(f"Total RTH unique minutes: {total_rth_unique_minutes:,}")
    print(f"Total RTH 1s bars: {len(df_rth):,}")
