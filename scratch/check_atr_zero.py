import pandas as pd
from pathlib import Path
from nautilus_trader.persistence.catalog import ParquetDataCatalog
from nautilus_trader.indicators import AverageTrueRange

catalog_path = "data/catalog/NQ_v0_2020_2026"
catalog = ParquetDataCatalog(catalog_path)

load_start = pd.Timestamp("2020-01-01", tz="UTC") - pd.Timedelta(days=5)
load_end = pd.Timestamp("2020-03-10", tz="UTC")

print("Loading 1m bars...")
bars_1m = catalog.bars(
    bar_types=["NQ.XCME-1-MINUTE-LAST-EXTERNAL"],
    start=load_start, end=load_end
)
print(f"Loaded {len(bars_1m)} 1m bars.")

atr = AverageTrueRange(14)
count = 0
for bar in bars_1m:
    count += 1
    h = float(bar.high)
    l = float(bar.low)
    c = float(bar.close)
    atr.update_raw(h, l, c)
    if count >= 150 and atr.value == 0.0:
        print(f"ATR is 0.0 at bar {count}: ts={bar.ts_event}, H={h}, L={l}, C={c}")
        # Print a few bars before
        break
else:
    print("No bars had ATR = 0.0 after warmup.")
