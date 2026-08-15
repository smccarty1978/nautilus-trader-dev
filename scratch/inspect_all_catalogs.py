import pyarrow.parquet as pq
import pandas as pd
from pathlib import Path

catalog_root = Path('data/catalog')

print('Catalog Root:', catalog_root.resolve())
for cat_dir in sorted(catalog_root.iterdir()):
    if not cat_dir.is_dir() or cat_dir.name == '__pycache__':
        continue
    bar_dir = cat_dir / 'data' / 'bar'
    if not bar_dir.exists():
        # check if it's direct bar dir or legacy
        print(f'Catalog: {cat_dir.name} (No data/bar found)')
        continue
    print('=' * 75)
    print(f'CATALOG: {cat_dir.name}')
    for sub in sorted(bar_dir.iterdir()):
        if not sub.is_dir():
            continue
        files = list(sub.glob('*.parquet'))
        if not files:
            continue
        f = files[0]
        pf = pq.ParquetFile(f)
        head = pf.read_row_group(0).slice(0, 2).to_pandas()
        row0 = head.iloc[0]
        ts_init = row0['ts_init']
        ts_event = row0['ts_event']
        dt_init = str(pd.to_datetime(ts_init, unit='ns', utc=True))
        dt_event = str(pd.to_datetime(ts_event, unit='ns', utc=True))
        diff_ns = ts_init - ts_event
        print(f'  [{sub.name}] Rows: {pf.metadata.num_rows:,} | '
              f'ts_event={dt_event} -> ts_init={dt_init} (delta={diff_ns}ns, {diff_ns/1e9}s)')
