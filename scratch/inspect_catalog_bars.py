import pyarrow.parquet as pq
import pandas as pd
from pathlib import Path

catalog_dirs = [
    'data/catalog/NQ_v0_2020_2026/data/bar/NQ.XCME-1-SECOND-LAST-EXTERNAL',
    'data/catalog/NQ_v0_2020_2026/data/bar/NQ.XCME-1-MINUTE-LAST-EXTERNAL',
    'data/catalog/NQ_v0_2020_2026/data/bar/NQ.XCME-5-MINUTE-LAST-EXTERNAL',
]

for cd in catalog_dirs:
    p = Path(cd)
    pq_files = list(p.glob('*.parquet'))
    if not pq_files:
        continue
    f = pq_files[0]
    pf = pq.ParquetFile(f)
    print('=' * 75)
    print(f'CATALOG BAR: {p.name}')
    print(f'File: {f.name} (Rows: {pf.metadata.num_rows:,})')
    print(f'Schema fields: {pf.schema.names}')
    
    head = pf.read_row_group(0).slice(0, 5).to_pandas()
    print('\nFirst 5 rows:')
    for idx, row in head.iterrows():
        ts_init = row.get('ts_init')
        ts_event = row.get('ts_event')
        dt_init = str(pd.to_datetime(ts_init, unit='ns', utc=True))
        dt_event = str(pd.to_datetime(ts_event, unit='ns', utc=True))
        diff_ns = ts_init - ts_event
        c = row.get('close')
        v = row.get('volume')
        print(f'  ts_init={dt_init} | ts_event={dt_event} | delta={diff_ns}ns ({diff_ns/1e9}s) | C={c} V={v}')
