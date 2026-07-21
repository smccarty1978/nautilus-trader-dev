import pandas as pd
from pathlib import Path
from nautilus_trader.persistence.catalog import ParquetDataCatalog

def run():
    catalog_path = "data/catalog/NQ_v0_2020_2026"
    catalog = ParquetDataCatalog(catalog_path)
    bars_1m = catalog.bars(
        bar_types=["NQ.XCME-1-MINUTE-LAST-EXTERNAL"],
        start=pd.Timestamp("2025-01-02", tz="UTC"),
        end=pd.Timestamp("2025-01-02 01:00:00", tz="UTC")
    )
    print("Total bars:", len(bars_1m))
    for i in range(min(10, len(bars_1m))):
        b = bars_1m[i]
        print(f"Bar {i}: ts_event={b.ts_event} ts_init={b.ts_init} diff={b.ts_init - b.ts_event} | open={b.open} close={b.close}")

if __name__ == "__main__":
    run()
