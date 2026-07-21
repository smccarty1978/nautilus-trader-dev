"""Run the stair-step exit replay over a year and save per-(entry,version) rows.

    python studies/stairstep_exits/run_matrix.py --year 2021
    python studies/stairstep_exits/run_matrix.py --year 2021 --smoke 5
"""
import argparse, os, sys, time
from pathlib import Path

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root)); os.chdir(project_root)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import numpy as np
import pandas as pd
from nautilus_trader.persistence.catalog import ParquetDataCatalog

sys.path.insert(0, str(Path(__file__).parent))
from replay import StairStepReplay  # noqa: E402

CATALOG = "data/catalog/NQ_v0_2020_2026"
BAR_TYPE = "NQ.XCME-1-SECOND-LAST-EXTERNAL"
OUT = Path("studies/stairstep_exits/results")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", type=int, required=True)
    ap.add_argument("--lead-in-days", type=int, default=3)
    ap.add_argument("--smoke", type=int, default=0)
    args = ap.parse_args()
    year = args.year
    OUT.mkdir(parents=True, exist_ok=True)

    load_start = pd.Timestamp(f"{year}-01-01", tz="UTC") - pd.Timedelta(days=args.lead_in_days)
    load_end = (pd.Timestamp(f"{year}-01-01", tz="UTC") + pd.Timedelta(days=args.smoke)
                if args.smoke else pd.Timestamp(f"{year}-12-31 23:59:59", tz="UTC"))
    print(f"Year {year} load {load_start}..{load_end}{' [SMOKE]' if args.smoke else ''}")

    catalog = ParquetDataCatalog(CATALOG)
    t0 = time.time()
    bars = catalog.bars(bar_types=[BAR_TYPE], start=load_start, end=load_end)
    print(f"  loaded {len(bars):,} 1s bars ({time.time()-t0:.0f}s)")
    if not bars:
        return

    t0 = time.time()
    o = np.fromiter((float(b.open) for b in bars), dtype=np.float64, count=len(bars))
    h = np.fromiter((float(b.high) for b in bars), dtype=np.float64, count=len(bars))
    l = np.fromiter((float(b.low) for b in bars), dtype=np.float64, count=len(bars))
    c = np.fromiter((float(b.close) for b in bars), dtype=np.float64, count=len(bars))
    v = np.fromiter((float(b.volume) for b in bars), dtype=np.float64, count=len(bars))
    tse = np.fromiter((int(b.ts_event) for b in bars), dtype=np.int64, count=len(bars))
    tsi = np.fromiter((int(b.ts_init) for b in bars), dtype=np.int64, count=len(bars))
    del bars
    print(f"  extracted arrays ({time.time()-t0:.0f}s)")

    rep = StairStepReplay()
    t0 = time.time()
    for i in range(len(c)):
        rep.on_bar(o[i], h[i], l[i], c[i], v[i], tse[i], tsi[i])
    rep.finalize()
    print(f"  replay done ({time.time()-t0:.0f}s); records={len(rep.records):,}")

    df = pd.DataFrame(rep.records)
    yr0 = pd.Timestamp(f"{year}-01-01", tz="UTC").value
    yr1 = pd.Timestamp(f"{year}-12-31 23:59:59", tz="UTC").value
    df = df[(df.entry_ts >= yr0) & (df.entry_ts <= yr1)].copy()
    suffix = f"_smoke{args.smoke}" if args.smoke else ""
    p = OUT / f"exit_outcomes_{year}{suffix}.parquet"
    df.to_parquet(p, index=False)
    print(f"  in-year rows={len(df):,} -> {p}")
    # quick orientation
    ent = df.drop_duplicates("entry_id")
    print(f"  entries: A={int((ent.population=='A').sum()):,} B={int((ent.population=='B').sum()):,}")
    print(f"  exit_reason mix (V1_ladder): "
          f"{df[df.version=='V1_ladder']['exit_reason'].value_counts().to_dict()}")


if __name__ == "__main__":
    main()
