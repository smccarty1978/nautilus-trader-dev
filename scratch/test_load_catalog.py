import time
import pandas as pd
from pathlib import Path
from nautilus_trader.persistence.catalog import ParquetDataCatalog

t_load = time.time()
catalog_path = Path("data/catalog/NQ_v0_2020_2026")
print("Loading catalog...")
catalog = ParquetDataCatalog(str(catalog_path))
print("Loading 1s NQ bars for 2025...")
load_start = pd.Timestamp("2025-01-01", tz="UTC")
load_end = pd.Timestamp("2025-01-02", tz="UTC") # just 1 day
bars_1s = catalog.bars(
    bar_types=["NQ.XCME-1-SECOND-LAST-EXTERNAL"],
    start=load_start,
    end=load_end
)
print(f"Loaded {len(bars_1s):,} bars in {time.time() - t_load:.2f}s")
