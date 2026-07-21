import pandas as pd
from pathlib import Path
from nautilus_trader.persistence.catalog import ParquetDataCatalog

catalog_path = "data/catalog/NQ_v0_2020_2026"
catalog = ParquetDataCatalog(catalog_path)

print("Loading 1s bars for 2026...")
load_start = pd.Timestamp("2026-01-01", tz="UTC")
load_end = pd.Timestamp("2026-12-31 23:59:59", tz="UTC")
bars_1s = catalog.bars(
    bar_types=["NQ.XCME-1-SECOND-LAST-EXTERNAL"],
    start=load_start, end=load_end
)
print(f"Loaded {len(bars_1s):,} 1s bars")

if len(bars_1s) > 0:
    first_bar = bars_1s[0]
    last_bar = bars_1s[-1]
    print(f"First bar timestamp: {pd.to_datetime(first_bar.ts_event, unit='ns', utc=True)}")
    print(f"Last bar timestamp: {pd.to_datetime(last_bar.ts_event, unit='ns', utc=True)}")
