"""Build ES.v.0 catalog covering 2020-2026 YTD.

Mirror of archive/scripts/build_v0_multi_year_catalog.py for ES instead
of NQ. Same resample semantics (label='left', closed='left'); only the
instrument multiplier differs ($50/pt for ES vs $20/pt for NQ).

Output: data/catalog/ES_v0_2020_2026/
"""
from __future__ import annotations
import os, sys, time, gc
from pathlib import Path
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))
os.chdir(project_root)

from nautilus_trader.persistence.catalog import ParquetDataCatalog
from nautilus_trader.persistence.wranglers import BarDataWrangler
from nautilus_trader.test_kit.providers import TestInstrumentProvider
from nautilus_trader.model.instruments import FuturesContract
from nautilus_trader.model.data import BarType

YEARS = [2020, 2021, 2022, 2023, 2024, 2025]
RAW_2026 = "data/raw/ES_v0_1s_2026_ytd.parquet"
OUT_DIR = Path("data/catalog/ES_v0_2020_2026")


def create_es_v0():
    t = TestInstrumentProvider.future(
        symbol="ES", underlying="ES", venue="XCME", exchange="XCME")
    d = t.to_dict(t)
    d["activation_ns"] = pd.Timestamp("2020-01-01", tz="UTC").value
    d["expiration_ns"] = pd.Timestamp("2027-01-01", tz="UTC").value
    d["ts_event"] = d["ts_init"] = pd.Timestamp("2020-01-01", tz="UTC").value
    d["multiplier"], d["price_increment"] = "50", "0.25"
    return FuturesContract.from_dict(d)


def aggregate_1m(df: pd.DataFrame) -> pd.DataFrame:
    agg = {"open": "first", "high": "max", "low": "min",
           "close": "last", "volume": "sum"}
    return df[list(agg)].resample("1min", label="left").agg(agg).dropna()


def main():
    t0 = time.time()
    print("=" * 78)
    print(f"BUILDING MULTI-YEAR ES.v.0 CATALOG -> {OUT_DIR}")
    print("=" * 78)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    catalog = ParquetDataCatalog(str(OUT_DIR))
    es = create_es_v0()
    catalog.write_data([es])
    print(f"Instrument: {es.id}  multiplier={es.multiplier}  "
          f"activation={pd.Timestamp(es.activation_ns, unit='ns', tz='UTC')}")

    print("\nLoading 1s parquet files...")
    parts = []
    for yr in YEARS:
        p = f"data/raw/ES_v0_1s_{yr}.parquet"
        df = pd.read_parquet(p, columns=["open","high","low","close","volume"])
        if df.index.tz is None:
            df.index = df.index.tz_localize("UTC")
        print(f"  {yr}: {len(df):,} rows")
        parts.append(df)
    if Path(RAW_2026).exists():
        df = pd.read_parquet(RAW_2026, columns=["open","high","low","close","volume"])
        if df.index.tz is None:
            df.index = df.index.tz_localize("UTC")
        print(f"  2026_ytd: {len(df):,} rows")
        parts.append(df)

    df_full = pd.concat(parts).sort_index()
    df_full = df_full[~df_full.index.duplicated(keep="first")]
    print(f"  combined: {len(df_full):,} 1s rows  range "
          f"{df_full.index.min()} -> {df_full.index.max()}")
    del parts; gc.collect()

    print("\nWrangling 1s bars...")
    bt_1s = BarType.from_str(f"{es.id}-1-SECOND-LAST-EXTERNAL")
    w_1s = BarDataWrangler(bar_type=bt_1s, instrument=es)
    bars_1s = w_1s.process(df_full, ts_init_delta=1_000_000_000)
    print(f"  {len(bars_1s):,} bars")
    catalog.write_data(bars_1s)
    del bars_1s; gc.collect()

    print("\nResampling to 1m...")
    df_1m = aggregate_1m(df_full)
    print(f"  {len(df_1m):,} 1m bars")
    bt_1m = BarType.from_str(f"{es.id}-1-MINUTE-LAST-EXTERNAL")
    w_1m = BarDataWrangler(bar_type=bt_1m, instrument=es)
    bars_1m = w_1m.process(df_1m, ts_init_delta=60_000_000_000)
    catalog.write_data(bars_1m)
    del bars_1m, df_1m; gc.collect()

    print("\nResampling to 5m...")
    df_5m = df_full[["open","high","low","close","volume"]].resample(
        "5min", label="left").agg({
        "open": "first", "high": "max", "low": "min",
        "close": "last", "volume": "sum",
    }).dropna()
    print(f"  {len(df_5m):,} 5m bars")
    bt_5m = BarType.from_str(f"{es.id}-5-MINUTE-LAST-EXTERNAL")
    w_5m = BarDataWrangler(bar_type=bt_5m, instrument=es)
    bars_5m = w_5m.process(df_5m, ts_init_delta=300_000_000_000)
    catalog.write_data(bars_5m)
    print(f"  wrote {len(bars_5m):,} 5m bars")

    print(f"\n[done] runtime: {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
